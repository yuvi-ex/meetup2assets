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

**The presenter types the SHORT NAME in the left column — nothing else.** Treat any of
these bare words as "run that step now". They are also real symlinks in this folder, so
`./install_vs` works in a shell too, but the presenter will not be typing a shell.

| Presenter types | Run | Say afterwards |
|---|---|---|
| `preflight` | `./00_preflight.sh` | Which checks passed; flag anything amber |
| `install_vs` | `./01_install_vs.sh` | The two scripts created, and that Rust is not in `exasol slc list` |
| `load_mongodb` | `./02_load_mongodb.sh` | 250 documents, nested objects, nothing flattened |
| `load_superstore` | `./02b_load_superstore.sh` | 51,290 lines, 24.5% lose money, −$920,646 |
| `load_exasol` | `./03_load_exasol.sh` | 2,500 transactions, and that DELIVERY_DAYS is NULL on 714 by design |
| `create_virtual_schema` | `./04_create_virtual_schema.sh` | One collection → four tables; explain `x\|object` and `x\|array` |
| `the_question` | `./05_the_question.sh` | Premium/Gold detail rows; top-10 spend vs the CRM's LTV; revenue by city and category |
| `dashboard` | `./06_dashboard.sh` | Six boards, all GO, give the URLs |
| `ml_udf` | `./07_ml_udf.sh` | ROC AUC 0.9798; the calibration table (0.1% vs 99.5%) |

Plain English still works ("ask the question", "load the customers into mongo") and maps to
the same rows. Never ask which script they meant when the short name is unambiguous — just run it.

## Lead every reply with THE QUESTION

**The presenter cannot see the terminal output — the room reads YOUR REPLY.** So the question
each step answers must appear in your text, not only in the script's output. Open every step
reply with the question as a bold heading and one line naming which engine holds which half,
then the numbers as a table. `05_the_question.sh` prints these in the terminal too; restate
them regardless.

For `the_question`, the four headings are:
1. **Show me the transactions and customer details for Premium / Gold** — the WHERE filters MongoDB fields, the ORDER BY sorts an Exasol one.
2. **Who are our top 10 customers by real spend, and does the CRM agree?** — no: the top three spent an identical ₹128,970 and are filed Bronze / Gold / Silver.
3. **Which city and category earn the money?** — order counts are flat 62–64; the entire gap is discount.
4. **Did Exasol just copy MongoDB overnight?** — no: the filter is pushed down, no credentials in the plan. Optional closer.

Every column in step 5 is aliased `MONGO_*` or `EXASOL_*` so the projector shows which
engine each value came from. Keep the prefixes when you write ad-hoc SQL for the room.

Say "transactions" for the Exasol side in Act 1 (steps 2–5). In Act 2 (steps 6–7) the order
lines live in MongoDB instead — flag that switch out loud rather than letting the room notice it.

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

**Prefer `ML.LOSS_SCORE` when the SQL itself is the point.** It is a SCALAR twin over the
same pickle — same features, same answer — so it drops into a SELECT list beside any other
column and needs no subquery. Use it for "show me the riskiest X" questions; use the SET
script above only when scoring all 51,290 lines:

```sql
SELECT o."order_id", ROUND(o."profit", 0) AS "ACTUAL_PROFIT",
       ROUND("ML"."LOSS_SCORE"(o."discount", o."quantity", o."sales", o."shipping_cost",
             o."category", o."sub_category", o."market", o."region",
             o."ship_mode", o."segment"), 4) AS "LOSS_RISK"
FROM "MONGO_SUPERSTORE"."ORDERS" o
WHERE o."market" = 'EU'
ORDER BY "LOSS_RISK" DESC
```

`ML.SCORED_LINES` is a view over the batched call, for aggregate questions — a plain
`GROUP BY` against it never mentions a model. `RETURNS` is a reserved word, so never alias
a column `AS RETURNS`.

## Facts you may state (all verified — do not recompute live)

- Superstore: 51,290 lines, 24.5% lose money, −$920,646 total.
- Model: ROC AUC 0.9798, average precision 0.9440. Band <0.10 → 0.1% actually lost money;
  band ≥0.90 → 99.5%, holding −$651,839 (71% of all losses in 13.6% of lines).
  These are REPRODUCIBLE as of 2026-09-04: `ml/export_training_data.sql` now sorts on
  "row_id". Before that the unordered virtual-schema scan reshuffled the train/test
  split every run and the metric wandered (0.9792 / 0.9796 / 0.9802).
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
