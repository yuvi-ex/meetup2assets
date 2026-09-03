#!/usr/bin/env bash
# STEP 7 — a model, trained on screen, that the database runs.
#
#   train.py  ->  loss_model.pkl  ->  BucketFS  ->  a SQL function  ->  ask in English
#
# Everything here is visible: the audience reads the script, watches it train,
# sees the file land in BucketFS, and then queries it without writing SQL.
source "$(dirname "$0")/lib/common.sh"
ML="$(dirname "$0")/ml"

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
node_ssh 'mkdir -p /var/lib/exa/bucketfs/bfsdefault/ml'
node_scp "$ML/loss_model.pkl" /var/lib/exa/bucketfs/bfsdefault/ml/loss_model.pkl
node_scp "$ML/loss_model.meta.json" /var/lib/exa/bucketfs/bfsdefault/ml/loss_model.meta.json
sleep 3
node_ssh 'ls -l /var/lib/exa/bucketfs/bfsdefault/ml/' | sed 's/^/    /'
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

cat <<'NOTE'

    Read the table as calibration, not accuracy: the band the model calls safe
    lost money on 0.1% of lines; the band it flags lost money on 99.6%.

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
