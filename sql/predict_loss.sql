CREATE OR REPLACE PYTHON3 SET SCRIPT ML.PREDICT_LOSS(
  order_id      VARCHAR(50),
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
EMITS (ORDER_ID VARCHAR(50), LOSS_PROB DOUBLE) AS
import joblib

# Loaded ONCE per UDF virtual machine, straight out of BucketFS — not per row.
MODEL = joblib.load('/buckets/bfsdefault/ml/loss_model.pkl')
NUM = ["discount", "quantity", "sales", "shipping_cost"]
CAT = ["category", "sub_category", "market", "region", "ship_mode", "segment"]

def run(ctx):
    df = ctx.get_dataframe(num_rows='all')
    if df is None or len(df) == 0:
        return
    df.columns = ["order_id"] + NUM + CAT
    X = df[NUM + CAT].copy()
    for c in NUM:
        X[c] = X[c].astype(float)
    proba = MODEL.predict_proba(X)[:, 1]
    out = df[["order_id"]].copy()
    out["loss_prob"] = proba
    ctx.emit(out)
/
