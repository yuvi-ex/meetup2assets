# Virtual Schema — live demo

Exasol queries MongoDB with no copy, joins it to a relational table in one SELECT,
serves six dashboards off that join, and runs a scikit-learn model inside the database.

> **Before you run anything, check your platform version.**
> This kit works on Exasol Personal **2.2.0** and fails on deployments migrated
> to **2.3.0-rc2** or later, which removed `.connection.sshPort` and moved
> BucketFS. One command tells you which you are on:
> ```sh
> jq -r '.connection.sshPort // "ABSENT -- migrated, this kit will fail"' \
>   "$HOME/.exasol/personal/deployments/default/deployment.json"
> ```
> Full detail, verified figures and the other prerequisites:
> **[SYSTEM_REQUIREMENTS.md](SYSTEM_REQUIREMENTS.md)**.
>
> Step 6 additionally needs `~/exasol-recipes`, which **nothing in this repo
> installs** — see the same file.

**Run the steps from the Command Palette:** `Cmd+Shift+P` → *Tasks: Run Task* → pick a number.
Or in the terminal: `./01_install_vs.sh` and so on.

| Step | Script | What the room sees | Time |
|---|---|---|---|
| 0 | `00_preflight.sh` | Green checks, or the one thing that will break | — |
| 1 | `01_install_vs.sh` | Rust SLC → adapter built → BucketFS → 2 SQL scripts | 6 min |
| 2 | `02_load_mongodb.sh` | 250 nested documents into MongoDB | 4 min |
| 3 | `03_load_exasol.sh` | 2,500 order lines into a typed Exasol table | 3 min |
| 4 | `04_create_virtual_schema.sh` | One collection becomes four SQL tables | 5 min |
| 5 | `05_the_question.sh` | **The join. The CRM contradicts the orders.** | 9 min |
| 6 | `06_dashboard.sh` | Six persona dashboards on that join | 8 min |
| 7 | `07_ml_udf.sh` | **train.py → .pkl → BucketFS → SQL → ask the AI** | 10 min |
| — | `99_reset.sh` | Undo steps 2–6 | — |
| — | `99_reset_ml.sh` | Undo step 7 only | — |

Full narration, expected output and the gotchas: **[RUNSHEET.md](RUNSHEET.md)** — open the
preview with `Cmd+Shift+V`.

## Files worth opening on screen

| Path | Why it matters |
|---|---|
| `ml/train.py` | Ordinary scikit-learn. **No Exasol-specific code in it at all.** |
| `ml/export_training_data.sql` | Training rows pulled out of MongoDB by SQL |
| `ml/Dockerfile` | Pinned to the exact versions the Exasol Python SLC ships |
| `sql/predict_loss.sql` | The UDF — model loaded once per process, scores a DataFrame |
| `sql/orders_enriched.sql` | The join, as a view: Exasol facts × MongoDB documents |
| `lib/common.sh` | Shared helpers; every gotcha is a comment here |

## The two addresses that break people

- `192.168.64.1` in the connection string, never `127.0.0.1` — it is dialled from
  inside the Exasol VM.
- BucketFS is a **directory** on the node: `/var/lib/exa/bucketfs/<service>/<bucket>/`,
  read by UDFs as `/buckets/<service>/<bucket>/`.

## Ask the AI (step 7's finish)

With the `exasol` MCP server connected, in plain English:

1. *What user-defined functions exist in the ML schema, and what does ML.PREDICT_LOSS take?*
2. *Use ML.PREDICT_LOSS to find the 10 riskiest Furniture order lines in the EU market.*
3. *How much of Superstore's total loss sits in lines the model scores above 0.9?*
