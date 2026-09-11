#!/usr/bin/env bash
# STEP 7 — a model, trained on screen, that the database runs.
#
#   train.py  ->  loss_model.pkl  ->  BucketFS  ->  a SQL function  ->  ask in English
#
# Everything here is visible: the audience reads the script, watches it train,
# sees the file land in BucketFS, and then queries it without writing SQL.
source "$(dirname "$0")/lib/common.sh"
ML="$(dirname "$0")/ml"

# Two prerequisites that are NOT part of this script's story but stop it dead.
# Both were hit on 2026-09-03 running step 7 on its own; run_all.sh happens to
# satisfy the second because it runs 02b first.
say "7pre. Prerequisites"
# Step 6 leaves ~18 of the 20 licensed connections parked as idle dash-server
# sessions, which starves everything below. Reclaim them first.
free_connections
# a) The PYTHON3 script-language container. SCRIPT_LANGUAGES advertises
#    PYTHON3=builtin_python3 whether or not a container exists, so every Python
#    UDF fails with "No usable script language container is installed" while the
#    alias looks perfectly healthy. `exasol slc list` is the only honest check.
if exasol slc list --deployment-dir "$DEPLOY_DIR" 2>/dev/null \
     | awk '/^python-3/ {print $NF}' | grep -qx yes; then
  ok "PYTHON3 SLC already installed"
else
  warn "installing the PYTHON3 SLC — THIS RESTARTS THE DATABASE (~90s)"
  warn "connections drop, the ssh port changes, dashboards error until it is back"
  # --auto-approve: the confirm prompt needs a TTY and an agent console has none,
  # so without it the installer exits 0 having done nothing ("Aborted; no changes
  # were made"). Note the flavor name is rejected: the alias PYTHON3 is required.
  exasol slc install PYTHON3 --auto-approve --deployment-dir "$DEPLOY_DIR"
  ok "PYTHON3 registered — ssh port is now $(ssh_port)"
fi
# b) The superstore virtual schema. Every query below reads MONGO_SUPERSTORE.
xsql -c "SELECT SCHEMA_NAME FROM EXA_ALL_VIRTUAL_SCHEMAS;" | grep -q MONGO_SUPERSTORE \
  && ok "MONGO_SUPERSTORE present" \
  || die "MONGO_SUPERSTORE missing — run ./02b_load_superstore.sh first"

say "7a. What the database already has (nothing was installed for this)"
xsql -c "
CREATE SCHEMA IF NOT EXISTS ML;
CREATE OR REPLACE PYTHON3 SCALAR SCRIPT ML.PROBE(dummy INT) EMITS (LIBRARY VARCHAR(60), VERSION VARCHAR(60)) AS
import sys, importlib
def run(ctx):
    ctx.emit('python', sys.version.split()[0])
    for m in ('numpy','pandas','scipy','sklearn','joblib'):
        try: ctx.emit(m, getattr(importlib.import_module(m), '__version__', 'builtin'))
        except Exception: ctx.emit(m, 'MISSING')
/
SELECT LIBRARY, VERSION FROM (SELECT ML.PROBE(1) FROM DUAL);" | xtable
ok "the Python SLC ships the data-science stack — nothing to pip install"

say "7b. Read train.py to the room"
echo "    ${ML}/train.py  — 60 lines, no Exasol-specific code in it at all"
sed -n '1,30p' "$ML/train.py" | sed 's/^/    /'
echo "    ..."

say "7c. Pull the training rows OUT OF MONGODB with SQL"
exapump sql -p starter-kit -f csv - < "$ML/export_training_data.sql" > "$ML/superstore_train.csv"
ok "$(( $(wc -l < "$ML/superstore_train.csv") - 1 )) order lines exported through the virtual schema"

say "7d. Train it, live"
# Build the pinned image if it is not on this machine yet (~2 min, once). After
# that Docker has it cached and the live run is seconds of fitting, not pip.
if ! docker image inspect exasol-ml-train >/dev/null 2>&1; then
  warn "building the pinned training image — first run only"
  docker build -q -t exasol-ml-train "$ML" >/dev/null
  ok "image exasol-ml-train built"
fi
# The image is pre-built and pinned to the SLC's exact library versions, so this
# is seconds of fitting rather than minutes of pip.
docker run --rm -v "$ML:/work" -w /work exasol-ml-train python train.py

say "7e. The artifact"
ls -lh "$ML/loss_model.pkl" | awk '{print "    " $9 "   " $5}'
cat "$ML/loss_model.meta.json" | sed 's/^/    /'

say "7f. Put it in BucketFS"
bucketfs_put "$ML/loss_model.pkl"       ml loss_model.pkl
bucketfs_put "$ML/loss_model.meta.json" ml loss_model.meta.json
sleep 3
bucketfs_ls ml | sed 's/^/    /'
ok "the UDF will read it at /buckets/bfsdefault/ml/loss_model.pkl"

say "7g. Define the function"
xsql -f "$(dirname "$0")/sql/predict_loss.sql" >/dev/null
ok "ML.PREDICT_LOSS created — model loaded ONCE per UDF process, not once per row"
# Without this the AI half of the demo dies silently: the MCP server connects as
# mcp_readonly, which cannot even SEE a UDF in a schema it has no rights on, so
# "what functions exist in ML?" comes back empty rather than erroring.
xsql -c "GRANT EXECUTE ON SCHEMA ML TO mcp_readonly;
         GRANT SELECT  ON SCHEMA ML TO mcp_readonly;" >/dev/null
ok "granted to mcp_readonly so the AI can discover and call it"

say "7h. Score 51,290 MongoDB documents from SQL"
xsql -f "$(dirname "$0")/sql/score_check.sql" | xtable

# --- THE LOGIC ---------------------------------------------------------------
# Everything above BUILDS the thing. 7i-7l explain it, because "the model runs
# in the database" is the claim people actually want to see justified.

say "7i. Where the model lives — it is a FILE the database can read"
bucketfs_ls ml | sed 's/^/    /'
ok "UDFs reach it at /buckets/bfsdefault/ml/loss_model.pkl — no service, no network"

say "7j. A SCALAR twin, so the model call fits in an ordinary SELECT"
# ML.PREDICT_LOSS is a SET script: Exasol forbids any other column in a SELECT
# that calls an EMITS script, so every call needs a CTE and a join back. Correct
# for scoring 51,290 rows, useless for SHOWING the idea. Same pickle, same
# features, same answer — only the call shape differs.
xsql -f "$(dirname "$0")/sql/loss_score_scalar.sql" >/dev/null
ok "ML.LOSS_SCORE created (SCALAR ... RETURNS DOUBLE)"
xsql -c "
SELECT o.\"order_id\"          AS ORDER_ID,
       o.\"sub_category\"      AS SUB_CATEGORY,
       ROUND(o.\"discount\",2) AS DISCOUNT,
       ROUND(o.\"profit\",0)   AS ACTUAL_PROFIT,
       ROUND(ML.LOSS_SCORE(o.\"discount\", o.\"quantity\", o.\"sales\",
             o.\"shipping_cost\", o.\"category\", o.\"sub_category\",
             o.\"market\", o.\"region\", o.\"ship_mode\",
             o.\"segment\"), 4) AS LOSS_RISK
FROM MONGO_SUPERSTORE.\"ORDERS\" o
WHERE o.\"category\" = 'Furniture' AND o.\"market\" = 'EU'
ORDER BY LOSS_RISK DESC LIMIT 5;" | xtable
ok "a prediction and the actual outcome side by side — on MongoDB documents"

say "7k. Wrap the batched call in a VIEW, and the model disappears"
xsql -c "
CREATE OR REPLACE VIEW ML.SCORED_LINES AS
WITH scored AS (
  SELECT ORDER_ID AS ROW_KEY, LOSS_PROB FROM (
    SELECT ML.PREDICT_LOSS(TO_CHAR(s.\"row_id\"), s.\"discount\", s.\"quantity\",
             s.\"sales\", s.\"shipping_cost\", s.\"category\", s.\"sub_category\",
             s.\"market\", s.\"region\", s.\"ship_mode\", s.\"segment\")
    FROM MONGO_SUPERSTORE.\"ORDERS\" s)
)
SELECT o.\"order_id\" AS ORDER_ID, o.\"category\" AS CATEGORY,
       o.\"sub_category\" AS SUB_CATEGORY, o.\"market\" AS MARKET,
       o.\"region\" AS REGION, o.\"discount\" AS DISCOUNT,
       o.\"sales\" AS SALES, o.\"profit\" AS PROFIT,
       sc.LOSS_PROB AS LOSS_RISK
FROM scored sc JOIN MONGO_SUPERSTORE.\"ORDERS\" o
  ON TO_CHAR(o.\"row_id\") = sc.ROW_KEY;" >/dev/null
xsql -c "GRANT SELECT ON SCHEMA ML TO mcp_readonly;" >/dev/null
ok "ML.SCORED_LINES created"
# A plain GROUP BY. Nothing in this query mentions a model.
xsql -c "
SELECT MARKET, COUNT(*) AS LINES_N,
       ROUND(100*AVG(CASE WHEN LOSS_RISK >= 0.9 THEN 1 ELSE 0 END),1) AS PCT_FLAGGED,
       ROUND(SUM(CASE WHEN LOSS_RISK >= 0.9 THEN PROFIT ELSE 0 END),0) AS FLAGGED_PROFIT
FROM ML.SCORED_LINES
GROUP BY 1 ORDER BY PCT_FLAGGED DESC;" | xtable
ok "anything that speaks SQL now reaches the model — BI tool, dashboard, or AI"

say "7l. The catalog knows both shapes, and can show you the source"
xsql -c "SELECT SCRIPT_NAME, SCRIPT_INPUT_TYPE AS CALL_SHAPE,
                SCRIPT_RESULT_TYPE AS RESULT_SHAPE
         FROM EXA_ALL_SCRIPTS WHERE SCRIPT_SCHEMA = 'ML' ORDER BY 1;" | xtable
echo "    SCRIPT_TEXT holds the source of any of them — that IS the model server:"
echo "      SELECT SCRIPT_TEXT FROM EXA_ALL_SCRIPTS WHERE SCRIPT_NAME = 'LOSS_SCORE';"
warn "RETURNS is a reserved word — 'AS RETURNS' as a column alias fails"

cat <<'LOGIC'

    THE LOGIC, in one paragraph. sklearn wrote a pickle. The pickle sits in
    BucketFS, which every node mounts as a local path. A UDF names that path and
    loads it ONCE per virtual machine, not once per row. Exasol then treats that
    UDF as a function, so the model is reachable by anything that can write SQL.
    The model never moves and the data never leaves.

    Two call shapes, chosen by intent:
      SCALAR ... RETURNS DOUBLE   reads like a built-in; use it to SHOW the idea
      SET    ... EMITS (...)      batches a dataframe; use it to SCORE at volume

    To port this to another model: change the feature list in the UDF and the
    path to the pickle. Nothing else here is specific to loss prediction.
LOGIC

cat <<'NOTE'

    Read the table as calibration, not accuracy: the band the model calls safe
    lost money on 0.1% of lines; the band it flags lost money on 99.5%.

    NOW HAND IT TO THE AI. In Claude Code or Claude Desktop, with the exasol
    MCP server connected, type these in plain English -- no SQL:

      "What user-defined functions exist in the ML schema, and what does
       ML.PREDICT_LOSS take?"

      "Use ML.PREDICT_LOSS to find the 10 riskiest Furniture order lines in
       the EU market, and show the discount on each."

      "How much of Superstore's total loss sits in lines the model scores
       above 0.9?"

    The assistant discovers the function through the MCP server, writes the SQL
    against MONGO_SUPERSTORE, and the model runs inside the database.
NOTE
say "STEP 7 DONE"
