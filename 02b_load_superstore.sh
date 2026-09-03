#!/usr/bin/env bash
# STEP 2b — the second MongoDB collection: 51,290 real Global Superstore order lines.
# Step 7's model trains on this. The retail data in step 2 is generated; this is not,
# and its discount -> loss signal is genuine, which is why the model is trained here.
source "$(dirname "$0")/lib/common.sh"

say "2b. Superstore into MongoDB"
[[ -f "$SUPERSTORE_JSON_GZ" ]] || die "missing $SUPERSTORE_JSON_GZ"
docker inspect -f '{{.State.Running}}' "$MONGO_CONTAINER" 2>/dev/null | grep -q true \
  || die "MongoDB is not running — run ./02_load_mongodb.sh first"

say "Converting to typed NDJSON"
# The source is 51,291 entries, the last of which is a {"Row ID": ""} trailer.
# Every value is a string, dates are DD-MM-YYYY, and 80% of rows have no postal code.
gunzip -c "$SUPERSTORE_JSON_GZ" > "$WORK/StoreSales.json"
python3 - "$WORK/StoreSales.json" "$WORK/superstore.ndjson" <<'PY'
import json, sys, datetime
rows = [r for r in json.load(open(sys.argv[1])) if r.get("Order ID")]
NAME = {"Row ID":"row_id","Order ID":"order_id","Order Date":"order_date","Ship Date":"ship_date",
        "Ship Mode":"ship_mode","Customer ID":"customer_id","Customer Name":"customer_name",
        "Segment":"segment","City":"city","State":"state","Country":"country",
        "Postal Code":"postal_code","Market":"market","Region":"region","Product ID":"product_id",
        "Category":"category","Sub-Category":"sub_category","Product Name":"product_name",
        "Sales":"sales","Quantity":"quantity","Discount":"discount","Profit":"profit",
        "Shipping Cost":"shipping_cost","Order Priority":"order_priority"}
INTS, FLOATS, DATES = {"row_id","quantity"}, {"sales","discount","profit","shipping_cost"}, {"order_date","ship_date"}
def parse(s):
    for f in ("%d-%m-%Y","%m/%d/%Y","%Y-%m-%d"):
        try: return datetime.datetime.strptime(s, f).strftime("%Y-%m-%dT00:00:00Z")
        except ValueError: pass
    raise SystemExit(f"unparseable date: {s!r}")
out = []
for r in rows:
    d = {}
    for k, v in r.items():
        k2 = NAME[k]
        if   k2 in DATES:  d[k2] = {"$date": parse(v)}
        elif k2 in INTS:   d[k2] = int(v)
        elif k2 in FLOATS: d[k2] = float(v)
        elif k2 == "postal_code":
            if v: d[k2] = v          # absent on the 41,296 non-US rows, not empty-string
        else: d[k2] = v
    out.append(d)
with open(sys.argv[2], "w") as f:
    for d in out: f.write(json.dumps(d) + "\n")
print(f"    {len(out):,} documents")
PY

say "Importing and indexing"
docker cp "$WORK/superstore.ndjson" "$MONGO_CONTAINER:/tmp/superstore.ndjson" >/dev/null
docker exec "$MONGO_CONTAINER" mongoimport --quiet -u root -p "$MONGO_ROOT_PW" \
  --authenticationDatabase admin --db superstore --collection orders --drop \
  --file /tmp/superstore.ndjson
mongo_root --eval "
db = db.getSiblingDB('superstore');
db.orders.createIndex({customer_id:1},{name:'customer_idx'});
db.orders.createIndex({order_date:-1},{name:'order_date_idx'});
db.orders.createIndex({category:1, sub_category:1},{name:'category_idx'});
db.orders.createIndex({market:1, region:1},{name:'market_idx'});
db.getSiblingDB('admin').grantRolesToUser('$MONGO_READER',[{role:'read',db:'superstore'}]);
print('    documents: ' + db.orders.countDocuments());"

say "Virtual schema over it"
xsql -c "
CREATE OR REPLACE CONNECTION MONGODB_SUPERSTORE
TO 'mongodb://$HOST_GATEWAY:27017/?authSource=admin&directConnection=true'
USER '$MONGO_READER' IDENTIFIED BY '$MONGO_READER_PW';
DROP VIRTUAL SCHEMA IF EXISTS MONGO_SUPERSTORE CASCADE;
CREATE VIRTUAL SCHEMA MONGO_SUPERSTORE
USING MONGODB_VS.MONGODB_ADAPTER WITH
  MONGODB_CONNECTION='MONGODB_SUPERSTORE'
  DATABASE='superstore'
  COLLECTION='orders'
  INFERENCE_SAMPLE_SIZE='500';" >/dev/null
xsql -c "SELECT COUNT(*) AS LINES_VISIBLE_FROM_SQL,
                SUM(CASE WHEN \"profit\" < 0 THEN 1 ELSE 0 END) AS LOSS_MAKING,
                ROUND(SUM(CASE WHEN \"profit\" < 0 THEN \"profit\" ELSE 0 END),0) AS LOSS_AMOUNT
         FROM MONGO_SUPERSTORE.\"ORDERS\";" | xtable
ok "MONGO_SUPERSTORE ready — this is what step 7 trains on"
say "STEP 2b DONE"
