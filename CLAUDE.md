# Live meetup demo — how to behave in this repo

You are being driven **in front of a live audience**. The presenter types plain English;
the room reads your replies on a projector. Optimise for that.

## Hard rules

1. **The audience reads your TEXT, not the terminal.** After every step, restate the key
   numbers in your reply as a short markdown table or a few bold lines. Never answer with
   "done — see the output above".
2. **Run the numbered scripts. Do not improvise equivalents.** Each step is a script in this
   folder and every figure in `RUNSHEET.md` came from it. Inventing your own SQL mid-demo
   risks a different number on screen than the presenter just promised.
3. **One step per request.** Do not run ahead. Never chain steps unless explicitly asked for
   "the whole thing".
4. **Never run `99_reset.sh` or `99_reset_ml.sh` unless the presenter says "reset" outright.**
5. **Keep replies short.** Three to six lines plus a table. No preamble, no restating the
   question. The room is reading, not scrolling.
6. If a step fails, say the one-line cause and the one-line fix from the "If something breaks"
   table in `RUNSHEET.md`. Do not start debugging live unless asked.
7. **Never print credentials** or the contents of `~/.exasol-starter-kit/credentials/`.

## The steps, and what each proves

| Ask sounds like | Run | Say afterwards |
|---|---|---|
| "check we're ready", "preflight" | `./00_preflight.sh` | Which checks passed; flag anything amber |
| "install the virtual schema" | `./01_install_vs.sh` | The two scripts created, and that Rust is not in `exasol slc list` |
| "load the customers into mongo" | `./02_load_mongodb.sh` | 250 documents, nested objects, nothing flattened |
| "load the orders into exasol" | `./03_load_exasol.sh` | 2,500 rows, and that DELIVERY_DAYS is NULL on 714 by design |
| "create the virtual schema" | `./04_create_virtual_schema.sh` | One collection → four tables; explain `x\|object` and `x\|array` |
| "ask the question", "join them" | `./05_the_question.sh` | Per-customer revenue is flat 0.3%; the CRM's LTV contradicts the orders |
| "build the dashboards" | `./06_dashboard.sh` | Six boards, all GO, give the URLs |
| "train the model", "show the UDF" | `./07_ml_udf.sh` | ROC AUC 0.9809; the calibration table (0.1% vs 99.6%) |

## After step 7 — the AI finale

The presenter will ask business questions in English. Answer them with SQL that calls
`ML.PREDICT_LOSS` over `MONGO_SUPERSTORE."ORDERS"`, using the `exasol` MCP tools (the read-only
user has EXECUTE on schema `ML`). Show the SQL you wrote **and** the result — the SQL is half
the point. Keep result sets to 10 rows unless asked otherwise.

`ML.PREDICT_LOSS` is a SET UDF:

```sql
SELECT "ORDER_ID", ROUND("LOSS_PROB",4) AS "LOSS_PROB" FROM (
  SELECT "ML"."PREDICT_LOSS"(s."order_id", s."discount", s."quantity", s."sales",
         s."shipping_cost", s."category", s."sub_category", s."market",
         s."region", s."ship_mode", s."segment")
  FROM "MONGO_SUPERSTORE"."ORDERS" s WHERE …)
ORDER BY "LOSS_PROB" DESC
```

A UDF that emits columns cannot have other columns in the same SELECT list — wrap it in a
subquery, always.

## Facts you may state (all verified — do not recompute live)

- Superstore: 51,290 lines, 24.5% lose money, −$920,646 total.
- Model: ROC AUC 0.9809, average precision 0.9470. Band <0.10 → 0.1% actually lost money;
  band ≥0.90 → 99.6%, holding −$656,277 (71% of all losses in 13.6% of lines).
- Retail join: ₹17.1M booked, ₹9.8M realised, ₹4.9M lost.
- Segment/tier revenue per customer: ₹68,501 / ₹68,446 / ₹68,300 — a 0.3% spread.
- MongoDB says 6× LTV spread and ~19 orders each; Exasol says 0.3% and exactly 10.

## Honesty — say it before someone in the room does

Both retail datasets are generated. The 8.1× "growth" in the trend chart is four months with
quantity fixed at 1/2/3/4; customer city is a proxy for product assignment; `RATING` is a
restatement of `DISCOUNT_PCT`; gross margin is a flat 45%. The **Superstore** data used for
the model is real and its discount→loss signal is genuine.

## Never

- Do not edit the scripts during the demo.
- Do not create new schemas, tables or dashboards unless asked.
- Do not open the artifact URL or claude.ai — the presenter uses local files.
