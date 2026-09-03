# Virtual Schema live demo — run-sheet

**35 minutes.** Run the numbered scripts one at a time so the room sees each step land.
`run_all.sh` is for rehearsal only. Every figure below was produced by these scripts.

    cd ~/meetup-virtual-schema
    ./00_preflight.sh          # the morning of the meetup

Preflight checks the six tools, that the database says `database_ready`, Docker, both data
files, and whether the RUST language and adapter are already installed — so you know whether
step 1 takes 20 seconds or 3 minutes.

---

## 01 — Install the Virtual Schema from the CLI  (6 min)

> "Exasol doesn't speak MongoDB out of the box. Three things have to be true: a Rust runtime,
> the adapter binary in BucketFS, and two SQL scripts. All of it from the command line."

    ./01_install_vs.sh

**1a. The Rust container.** Show this first — it surprises people:

    $ exasol slc list
    FLAVOR       ALIASES             VERSION  INSTALLED
    java-17      JAVA, JAVA17        11.2.0   no
    python-3.12  PYTHON3, PYTHON312  11.2.0   no
    r-4.4        R, R44              11.2.0   no

No Rust in the catalog. It comes from `exasol-labs/language-container-rs`; the script installs
the prebuilt v0.23.0 tarball over SSH and registers the language with `ALTER SYSTEM`, which
survives a restart.

**1b. Build the adapter, put it in BucketFS.**

    Artifact verified: Linux ELF, expected entry points,
    SLC fingerprint 0.23.0:rustc_1.94.1__e408947bf_2026-03-25_

**1c. Two SQL statements and it exists.**

    SCRIPT_NAME      SCRIPT_TYPE  SCRIPT_LANGUAGE
    MONGODB_ADAPTER  ADAPTER      RUST
    MONGODB_SCAN     UDF          RUST

> If asked: BucketFS on Personal is a DIRECTORY the engine reconciles into a bucket in ~1s.
> It starts empty, so the script mkdirs the bucket path before scp — otherwise scp fails with
> an opaque `dest open ... Failure`. The SSH port is re-assigned on every `exasol start`, so
> it is read fresh from deployment.json each run.

---

## 02 — Load MongoDB, documents stay documents  (4 min)

> "250 customers. Nested objects for location, loyalty and preferences. I am not flattening
> anything — that's the whole point."

    ./02_load_mongodb.sh

    { customer_id: 'C0004', name: 'Diya Nguyen',
      customer_segment: 'Standard', age_band: '18-25',
      location:    { city: 'Pune', state: 'MH', region: 'West' },
      loyalty:     { member: true, points: 1724, tier: 'Bronze' },
      preferences: { favorite_category: 'Electronics', ... },
      lifetime_value: 9992, order_count: 29, satisfaction_score: 4 }

**WILL BITE YOU.** `mongo:8.0` and `mongo:latest` will not boot on Docker Desktop's current
kernel (>= 6.19, SERVER-121912) — the container exits instantly with no obvious cause. The
script pins `mongo:8.2`.

**Why the script rewrites the JSON.** Integers are pinned to Int32 before import. Left as plain
JSON numbers MongoDB stores them as doubles, and the connector then exposes BOTH `salary` and
`salary|double` — it refuses to silently merge two BSON types into one column. Correct, but a
confusing thing to explain live.

---

## 03 — Load Exasol, an ordinary table  (3 min)

> "The order facts are relational and they belong in Exasol. Typed columns, a primary key, a
> bulk load. Nothing exotic."

    ./03_load_exasol.sh
    Imported 2500 rows

    ROWS_LOADED  CUSTOMERS  FROM_DAY    TO_DAY      DELIVERY_DAYS_PRESENT
    2500         250        2025-01-01  2025-10-27  1786

Point at the last column: 1,786 of 2,500. `DELIVERY_DAYS` is NULL for every Cancelled and
Processing line — structural, not dirty data, and why the boards never divide delivery time by
the full row count.

**WILL BITE YOU.** A CRLF CSV puts a trailing `\r` inside the last column, so `= 'Delivered'`
matches nothing while every row count still looks right. The script strips CRs and uppercases
the header before loading.

---

## 04 — Create the virtual schema, the moment  (5 min)

> "No DDL. No column list. No copy. Two statements, and 250 MongoDB documents are queryable
> SQL objects."

    ./04_create_virtual_schema.sh

    CREATE OR REPLACE CONNECTION MONGODB_RETAIL
    TO 'mongodb://192.168.64.1:27017/?authSource=admin'
    USER 'analytics_reader' IDENTIFIED BY '...';

    CREATE VIRTUAL SCHEMA MONGO_RETAIL
    USING MONGODB_VS.MONGODB_ADAPTER WITH
      MONGODB_CONNECTION='MONGODB_RETAIL'
      DATABASE='retail'
      COLLECTION='customers';

**One collection became four tables** — this is the slide that lands:

| Table                   | What it is                     | Joined by            |
|-------------------------|--------------------------------|----------------------|
| `CUSTOMERS`             | the root document              | —                    |
| `CUSTOMERS_location`    | embedded `location` object     | `location|object`    |
| `CUSTOMERS_loyalty`     | embedded `loyalty` object      | `loyalty|object`     |
| `CUSTOMERS_preferences` | embedded `preferences` object  | `preferences|object` |

Naming conventions people always ask about:

| Suffix                  | Meaning                                                          |
|-------------------------|------------------------------------------------------------------|
| `x|object`              | foreign key to that child table's `_id`                          |
| `x|array`               | the element COUNT — elements live in an `_arr` child table        |
| `x|empty`               | empty string, kept distinct from a missing field                 |
| `x|n`                   | an explicit JSON null, kept distinct from absent                 |
| `__mongodb_source_json` | the whole original document                                      |

**The one address that matters:** `192.168.64.1`, not `127.0.0.1`. The string is dialled from
INSIDE the Exasol VM, so localhost would resolve to the VM itself. Most common first failure.

---

## 05 — The question neither database can answer alone  (9 min)

> "Which customer segment and loyalty tier generate the most revenue? The segments live in
> MongoDB. The revenue lives in Exasol. Watch."

    ./05_the_question.sh

    SELECT c."customer_segment", l."tier",
           COUNT(DISTINCT c."customer_id")        AS CUSTOMERS,
           ROUND(SUM(o.REVENUE),0)                AS REVENUE,
           ROUND(SUM(o.REVENUE)/COUNT(DISTINCT c."customer_id"),0) AS REV_PER_CUSTOMER
    FROM RETAIL.ORDERS o                       -- Exasol, 2,500 rows
    JOIN MONGO_RETAIL."CUSTOMERS" c            -- MongoDB, live
           ON c."customer_id" = o.CUSTOMER_ID
    JOIN MONGO_RETAIL."CUSTOMERS_loyalty" l    -- the embedded object
           ON l."_id" = c."loyalty|object"
    GROUP BY 1,2 ORDER BY REVENUE DESC;

### Q1 — the answer that looks obvious

| Segment  | Tier   | Customers |    Revenue | Per customer | Rating | Returns |
|----------|--------|----------:|-----------:|-------------:|-------:|--------:|
| Premium  | Gold   |       100 | Rs6,850,080 |     Rs68,501 |   3.00 |   14.4% |
| Growth   | Silver |        94 | Rs6,433,900 |     Rs68,446 |   2.96 |   14.4% |
| Standard | Bronze |        56 | Rs3,824,825 |     Rs68,300 |   3.07 |   13.9% |

Premium/Gold earns the most — but only because it holds the most customers. Per customer the
three tiers are within **0.3%**. Ratings and returns don't follow either.

> "So the tiers are real in the CRM. Are they real in the money? Let's ask the two systems the
> same question and put the answers side by side."

### Q2 — the payoff: the CRM contradicts the orders

| Segment  | MongoDB says LTV | MongoDB says orders | Exasol says revenue | Exasol says orders |
|----------|-----------------:|--------------------:|--------------------:|-------------------:|
| Premium  |         Rs68,685 |                19.2 |            Rs68,501 |                 10 |
| Growth   |         Rs34,763 |                19.6 |            Rs68,446 |                 10 |
| Standard |         Rs11,323 |                19.8 |            Rs68,300 |                 10 |

The customer document claims a **6x value spread** and ~19 orders each. The order facts show a
**0.3% spread** and exactly 10 orders each. Neither system could have told you that alone — and
that is the argument for joining at query time on live data, instead of copying one into the
other and inheriting its errors.

### Q3 — nothing was copied

    predicate handed to MongoDB:
      "pushdown":{"prefilter":{"kind":"compare","op":"equal",
        "column":"customer_segment","literal":{..."value":"Premium"}}}
    credentials in the plan: NONE — only the connection name

Projection, filters, limits and top-N are pushed down; the plan names the connection, never the
password.

---

## 06 — Six dashboards on the same join  (8 min)

> "One view IS the join. Six audiences read it. Every tile you're about to see is a live
> MongoDB query."

    ./06_dashboard.sh
    ROWS_JOINED  CUSTOMERS  BOOKED     REALISED  LOST
    2500         250        17108805   9808944   4880883

| Board                | For                                                  |
|----------------------|------------------------------------------------------|
| `retail-finance`     | booked vs realised vs lost revenue                   |
| `retail-sales`       | store and channel performance                        |
| `retail-product`     | category and product line value                      |
| `retail-datascience` | which customer features survive a control — none do  |
| `retail-inventory`   | reorder pressure, and what it cannot tell you        |
| `retail-delivery`    | order pipeline and delivery tiers                    |

Open <http://127.0.0.1:5100/> and land on **retail-datascience** — it headlines the same
contradiction the SQL just showed, closing the loop from query to product.

> Why a view, not the virtual schema directly: dash-server reads as `mcp_readonly`, which has no
> rights on a virtual schema you just created. The join lives in `RETAIL.ORDERS_ENRICHED`, a view
> in a normal schema, granted to that user. Nothing is materialised.

---

## If something breaks

| Symptom                                  | Cause                                  | Fix, live                                        |
|------------------------------------------|----------------------------------------|--------------------------------------------------|
| Connection fails on CREATE VIRTUAL SCHEMA| SSH port changed, or gateway address    | `./00_preflight.sh`; confirm `192.168.64.1`      |
| Mongo container exits immediately        | image `8.0`/`latest` on kernel >= 6.19  | `MONGO_IMAGE=mongo:8.2 ./02_load_mongodb.sh`     |
| Every filter matches nothing             | CRLF in the CSV                         | handled in step 3 — mention it, don't debug it   |
| Dashboard 500s but MCP answers           | stale dash-server process               | `exakit stop && exakit start`                    |
| Board shows no rows                      | view missing or grant lost              | re-run `./06_dashboard.sh`                       |

## Honesty notes — say these before someone else does

Both datasets are generated and the generator shows through. Naming it costs 30 seconds and
buys the room's trust for everything else.

| Artifact      | What it looks like             | What it actually is                                            |
|---------------|--------------------------------|----------------------------------------------------------------|
| Trend chart   | 8.1x growth Jan to Oct         | four months only, 625 lines each, quantity fixed 1/2/3/4        |
| Customer city | 2.9x swing in line value       | each product sits in exactly one city band — city is a proxy    |
| `RATING`      | a satisfaction score           | a restatement of `DISCOUNT_PCT`: 0%->1 star ... 20%->5 stars    |
| Gross margin  | a mix lever                    | fixed 45.0% of revenue on every single line                     |

All four are already written into the boards as cards and into their "what this can't answer"
panels, so the dashboards say it for you.

## Reset between runs

    ./99_reset.sh    # drops the virtual schema, RETAIL, the connection, the collection
                     # keeps the Rust SLC, the adapter, the .so and the dashboards

A second run then starts at step 2 and takes about twelve minutes.

---

## 07 — A model, trained on screen, that the database runs  (10 min)

    ./07_ml_udf.sh        # the whole step takes ~11 seconds to execute

> "The model is going to run inside the database, on documents that live in MongoDB.
> Nothing leaves either system."

**7a. What Exasol already has.** `ML.PROBE` imports and prints versions from inside a UDF:

    LIBRARY  VERSION
    python   3.12.3
    numpy    1.26.4
    pandas   2.3.2
    scipy    1.16.2
    sklearn  1.7.2
    joblib   1.5.3

The Python SLC ships the data-science stack. Nothing to pip install into the database.

**7b. Read `ml/train.py` to the room.** 60 lines, ordinary scikit-learn, and *no Exasol-specific
code anywhere in it*. Target: `profit < 0`. Features are only what is knowable when the line is
placed — no profit, no cost, no margin.

**7c. Pull the training rows out of MongoDB with SQL.** `ml/export_training_data.sql` selects
51,290 rows from `MONGO_SUPERSTORE."ORDERS"` — the virtual schema is the data pipeline.

**7d. Train it, live.** Runs in a Docker image pinned to the SLC's exact versions:

    1/5  reading training rows exported from MongoDB
         51,290 order lines · 24.5% of them lost money
    2/5  splitting 75 / 25, stratified on the target
    3/5  fitting  one-hot -> gradient boosting
    4/5  ROC AUC 0.9809   average precision 0.9470   base rate 0.2446
    5/5  loss_model.pkl + loss_model.meta.json written

**WILL BITE YOU.** Train in the pinned container, never on the host. The local venv has
numpy 2.5.2 / sklearn 1.9.0; the SLC has 1.26.4 / 1.7.2. A pickle from the host will not load
inside the database.

**7e-7f. The artifact goes to BucketFS.** 116 KB, scp'd to
`/var/lib/exa/bucketfs/bfsdefault/ml/`, read by the UDF as `/buckets/bfsdefault/ml/loss_model.pkl`.

**7g. Define the function.** A PYTHON3 **SET** script: the model is loaded once per UDF process
at module scope, and each call scores a whole DataFrame — not one row at a time.

**7h. Score all 51,290 MongoDB documents from SQL.**

| Predicted risk    | Lines  | Actually lost money |    Sales | Loss     |
|-------------------|-------:|--------------------:|---------:|---------:|
| below 0.10        | 31,939 |            **0.1%** | 7,802,574|     -919 |
| 0.10-0.49         |  8,054 |               27.4% | 2,901,052|  -63,592 |
| 0.50-0.89         |  4,307 |               77.6% |   978,972| -199,858 |
| **flagged >=0.90**|  6,990 |           **99.6%** |   959,903| -656,277 |

Read it as calibration, not accuracy: the band the model calls safe lost money on 0.1% of lines;
the band it flags lost money on 99.6%. 13.6% of lines carry 71% of all losses.

### Then hand it to the AI

With the `exasol` MCP server connected, type these in plain English — no SQL:

1. "What user-defined functions exist in the ML schema, and what does ML.PREDICT_LOSS take?"
2. "Use ML.PREDICT_LOSS to find the 10 riskiest Furniture order lines in the EU market."
3. "How much of Superstore's total loss sits in lines the model scores above 0.9?"

The assistant discovers the function through MCP, writes the SQL against `MONGO_SUPERSTORE`,
and the model runs inside the database.

**WILL BITE YOU.** The MCP server connects as `mcp_readonly`, which cannot even *see* a UDF in
a schema it has no rights on — question 1 returns an empty list rather than an error. Step 7g
grants `EXECUTE` and `SELECT` on schema `ML` for exactly this reason.
