# Starter Kit demo — MongoDB Virtual Schema, dashboards, and a model in the database

Everything here runs on top of the
[Exasol Personal Local Starter Kit](https://github.com/exasol/local-agent-ready-starter):
a real Exasol database on your own laptop. The kit is the base. This repo adds
three things on top of it and shows them working together in about 35 minutes.

| On top of the kit | What it does |
|---|---|
| **MongoDB Virtual Schema** | Exasol queries MongoDB **live, with no copy and no ETL** — documents become SQL tables |
| **dash-server** | Six persona dashboards served off the Exasol × MongoDB join |
| **Python UDF** | A scikit-learn model trained on screen, then run **inside the database** |

The point of the demo: your relational facts stay in Exasol, your documents stay
in MongoDB, and you answer one question across both in a single SELECT.

## Run it

```sh
curl -fsSL https://raw.githubusercontent.com/yuvi-ex/starterkit-dashserver-VS-UDF/main/bootstrap.sh | sh
```

That is the whole thing: it gates on the platform limits below, clones into
`~/starterkit-vs-udf`, caches every download, then runs all seven steps.
Dashboards land on **http://127.0.0.1:5100/**.

Budget **about an hour for a first run** — most of that is downloading two
container images, two repositories and a 200 MB language container. Once those
are cached a full rebuild is under ten minutes.

> Verified end to end on 2026-09-15: this one command took a deleted directory
> to `ALL STEPS DONE`, with `RETAIL`, `MONGODB_VS`, `MONGO_RETAIL`,
> `MONGO_SUPERSTORE` and `ML` created and all six dashboards answering.

It never prompts, so an AI agent can run it — every failure exits non-zero
naming the one command that fixes it, and re-running is the repair. Add
`--install-kit` to install the starter kit and dash-server too.

**Presenting it? Do not use this.** Run the numbered steps one at a time so the
room sees each land — see [Run it step by step](#run-it-step-by-step).

---

## The MongoDB Virtual Schema

This is the centre of the demo, so it is worth being precise about what it is.

A **virtual schema** makes an external system look like a normal SQL schema
inside Exasol. Nothing is imported. When you query it, Exasol pushes filters and
projections down to MongoDB, gets rows back, and joins them to its own tables.

Creating it is two statements — no DDL, no column list, no copy:

```sql
CREATE OR REPLACE CONNECTION MONGODB_RETAIL
  TO 'mongodb://192.168.64.1:27017/?authSource=admin'
  USER 'analytics_reader' IDENTIFIED BY '...';

CREATE VIRTUAL SCHEMA MONGO_RETAIL
  USING MONGODB_VS.MONGODB_ADAPTER WITH
    MONGODB_CONNECTION = 'MONGODB_RETAIL'
    DATABASE   = 'retail'
    COLLECTION = 'customers';
```

**Nested documents become related tables automatically.** One `customers`
collection with `location`, `loyalty` and `preferences` objects inside each
document turns into four queryable tables:

| Table | What it is |
|---|---|
| `CUSTOMERS` | the root document |
| `CUSTOMERS_location` | the embedded `location` object |
| `CUSTOMERS_loyalty` | the embedded `loyalty` object |
| `CUSTOMERS_preferences` | the embedded `preferences` object |

You then join them to an ordinary Exasol table in one SELECT — and the payoff of
the demo is what that join reveals: **the CRM contradicts the orders.** Three
customers who each spent exactly the same amount are filed in MongoDB as Bronze,
Gold and Silver. Tier is assigned in one system, money is counted in the other,
and nothing had ever compared the two.

The adapter is Rust, which is not in Exasol's language catalog — step 1 installs
the language container and the adapter binary for you.

---

## Will this run on your laptop?

Be honest with yourself here rather than finding out on stage.

| Needs | Why |
|---|---|
| **Apple silicon Mac** | the prebuilt Rust container is `aarch64` only |
| **Exasol Personal 2.2.0** | 2.3.0-rc2 and later moved BucketFS; this kit fails there |
| **Docker running** | MongoDB runs in it (`mongo:8.2` or newer) |
| **~25 GB free disk, 16 GB RAM** | the VM, two language containers, images and data |

One command tells you whether your platform is the supported one:

```sh
jq -r '.connection.sshPort // "ABSENT -- migrated platform, this kit will fail"' \
  "$HOME/.exasol/personal/deployments/default/deployment.json"
```

Full detail: **[SYSTEM_REQUIREMENTS.md](SYSTEM_REQUIREMENTS.md)**.

## Run it step by step

This is the path for presenting: each step lands in front of the room.

```sh
./00_preflight.sh     # stops at the first blocker and names the fix
./00b_prefetch.sh     # the night before — caches every download
```

Then run the numbered steps one at a time so the room sees each land. In VS Code:
`Cmd+Shift+P` → *Tasks: Run Task* → pick a number.

| Step | Script | What the room sees | Time |
|---|---|---|---|
| 1 | `01_install_vs.sh` | Rust container → adapter → BucketFS → 2 SQL scripts | 6 min |
| 2 | `02_load_mongodb.sh` | 250 nested documents into MongoDB | 4 min |
| 2b | `02b_load_superstore.sh` | 51,290 Superstore docs — **step 7 needs this** | 3 min |
| 3 | `03_load_exasol.sh` | 2,500 order lines into a typed Exasol table | 3 min |
| 4 | `04_create_virtual_schema.sh` | **One collection becomes four SQL tables** | 5 min |
| 5 | `05_the_question.sh` | **The join. The CRM contradicts the orders.** | 9 min |
| 6 | `06_dashboard.sh` | Six persona dashboards on that join | 8 min |
| 7 | `07_ml_udf.sh` | train.py → .pkl → BucketFS → SQL → ask the AI | 10 min |

`run_all.sh` does the lot unattended — for rehearsal, not for the talk.
`99_reset.sh` undoes steps 2, 2b and 6; `99_reset_ml.sh` undoes step 7.

Dashboards land on <http://127.0.0.1:5100/>.

## Presenting it

| Doc | For |
|---|---|
| **[RUNSHEET.md](RUNSHEET.md)** | The full talk track: narration, expected output, every gotcha |
| **[DEMO_PROMPTS.md](DEMO_PROMPTS.md)** | The same demo driven entirely by asking an AI in plain English |
| **[SYSTEM_REQUIREMENTS.md](SYSTEM_REQUIREMENTS.md)** | The platform boundary, and what is verified |

Both datasets are generated and the generator shows through in places. RUNSHEET
lists exactly where, and the dashboards say it themselves in their own panels —
naming it costs thirty seconds and buys the room's trust for everything else.

## The two addresses that break people

- **`192.168.64.1`** in the MongoDB connection string, never `127.0.0.1` — the
  string is dialled from *inside* the Exasol VM, so localhost would be the VM.
- **BucketFS is a directory** on the node, `/var/lib/exa/bucketfs/<service>/<bucket>/`,
  which UDFs read as `/buckets/<service>/<bucket>/`.

## The model inside the database (step 7)

`ml/train.py` is ordinary scikit-learn with **no Exasol-specific code in it at
all**. Its training rows are pulled out of MongoDB by SQL, through the virtual
schema. The resulting `.pkl` goes into BucketFS, and a Python UDF scores all
51,290 documents from a SELECT — nothing leaves either database.

Read it as calibration: the band the model calls safe lost money on 0.1% of
lines; the band it flags lost money on 99.5%.

Sample data for demonstration purposes. `LICENSE` covers the code in this repo.
