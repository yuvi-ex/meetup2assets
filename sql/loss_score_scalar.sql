-- A SCALAR companion to ML.PREDICT_LOSS, for the part of the talk where the
-- POINT is the SQL rather than the throughput.
--
-- Same pickle, same features, same answer. The difference is the call shape:
--   SET  ... EMITS   -> must be alone in its SELECT, needs a CTE and a join back
--   SCALAR ... RETURNS -> drops into a SELECT list beside any other column
--
-- The model is still loaded ONCE per UDF virtual machine (module scope, not
-- inside run()), so this is not the naive per-row-unpickle version.
CREATE OR REPLACE PYTHON3 SCALAR SCRIPT ML.LOSS_SCORE(
  discount      DOUBLE,
  quantity      DECIMAL(10,0),
  sales         DOUBLE,
  shipping_cost DOUBLE,
  category      VARCHAR(100),
  sub_category  VARCHAR(100),
  market        VARCHAR(100),
  region        VARCHAR(100),
  ship_mode     VARCHAR(100),
  segment       VARCHAR(100))
RETURNS DOUBLE AS
import joblib
import pandas as pd

MODEL = joblib.load('/buckets/bfsdefault/ml/loss_model.pkl')
NUM = ["discount", "quantity", "sales", "shipping_cost"]
CAT = ["category", "sub_category", "market", "region", "ship_mode", "segment"]

def run(ctx):
    row = {
        "discount": float(ctx.discount), "quantity": float(ctx.quantity),
        "sales": float(ctx.sales), "shipping_cost": float(ctx.shipping_cost),
        "category": ctx.category, "sub_category": ctx.sub_category,
        "market": ctx.market, "region": ctx.region,
        "ship_mode": ctx.ship_mode, "segment": ctx.segment,
    }
    X = pd.DataFrame([row])[NUM + CAT]
    return float(MODEL.predict_proba(X)[0, 1])
/

GRANT EXECUTE ON SCHEMA ML TO mcp_readonly;
