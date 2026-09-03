# What to type, in order

Open a terminal, then:

    cd ~/meetup-virtual-schema
    claude

That's the only shell command in the entire demo, and you run it before anyone is watching.
Starting Claude Code in this folder loads `CLAUDE.md`, which is what keeps every run identical.

Everything below is typed into the Claude prompt in plain English. The room reads Claude's
replies on the projector.

---

## Opening  (before you type anything)

> "I have MongoDB running in a container with customer documents in it, and Exasol running
> natively with order data in it. Two databases, two shapes, no ETL between them. I'm going
> to make Exasol query MongoDB, join them in one SELECT, and then run a machine-learning model
> inside the database. And I'm not going to write any SQL — I'll just ask."

---

## 1 — Prove the room is real

**Type:** `check we're ready to demo`

Claude runs preflight. Point out that the SSH port changes on every database restart, which
is why nothing here hardcodes it.

## 2 — Install the connector  *(skip if pre-installed; say you did it beforehand)*

**Type:** `install the mongodb virtual schema`

While it runs: "Rust isn't even in Exasol's language catalog — `exasol slc list` offers Java,
Python and R. The adapter is Rust, so the container comes from Exasol Labs."

## 3 — The MongoDB side

**Type:** `load the customer documents into mongodb`

Claude shows one document. **Point at the nesting.** "location, loyalty, preferences — these
are objects inside the document. I am not flattening them. That's the whole point."

## 4 — The Exasol side

**Type:** `load the retail orders into exasol`

"2,500 order lines, typed columns, a primary key. Utterly ordinary."

## 5 — The moment

**Type:** `create the virtual schema over the mongodb collection`

**Let the four tables land, then pause.** "One collection. Four SQL tables. I wrote no DDL and
no column list, and nothing was copied — the documents are still in MongoDB."

Then: `what columns did it infer, and what do the pipe suffixes mean?`

## 6 — The payoff

**Type:** `which customer segment and loyalty tier generate the most revenue?`

Premium/Gold wins on revenue. Let that sit for a second.

**Then type:** `is that per customer, or just because there are more of them?`

Flat — 0.3%.

**Then the kill shot:** `does the CRM's own lifetime_value agree with the order data?`

MongoDB claims 6× and ~19 orders; Exasol says 0.3% and exactly 10.

> "Neither system could have told you that alone. That's why the join has to happen at query
> time, on live data, instead of copying one into the other and inheriting its errors."

**Then:** `prove nothing was copied — show me the pushdown`

## 7 — Dashboards

**Type:** `build the dashboards on that join`

Open one in the browser. Land on **retail-datascience** — it headlines the same contradiction.

## 8 — The model

**Before running it, open `ml/train.py` on screen and read it.**

> "Sixty lines of scikit-learn. There is not one line of Exasol-specific code in this file."

**Type:** `train the loss model and deploy it as a UDF`

Watch `loss_model.pkl` appear in the VS Code file tree while the training log prints.
Then the calibration table: safe band 0.1%, flagged band 99.6%.

## 9 — The finale: ask the model questions in English

**Type each of these:**

- `what user-defined functions exist in the ML schema, and what does ML.PREDICT_LOSS take?`
- `use the model to find the 10 riskiest Furniture order lines in the EU market, and show the discount on each`
- `how much of Superstore's total loss sits in lines the model scores above 0.9?`
- `which sub-category has the highest average predicted loss risk?`

> "The model is a pickle in BucketFS. The data is documents in MongoDB. The question was
> English. Nothing moved."

---

## If something goes wrong

Say to Claude: `that failed — what's the fix?` — it has the whole troubleshooting table.

**The three real risks, and what to say:**

| If | Say |
|---|---|
| Connection fails after a restart | "The SSH port moves on every restart — that's why we read it fresh." Re-run preflight. |
| Mongo container is dead | "MongoDB 8.0 won't boot on this kernel — pinned to 8.2." Re-run step 2. |
| A dashboard 500s | "Stale server process." `exakit stop && exakit start`, then move on to the AI questions. |

## Rehearse

Run every step once the morning of. Then `reset step 7` and `reset` to put it back, and leave
steps 1–4 installed so the live run starts at the interesting part.
