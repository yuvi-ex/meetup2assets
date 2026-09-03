#!/usr/bin/env bash
# STEP 2 — MongoDB side: 250 customer documents with nested objects.
source "$(dirname "$0")/lib/common.sh"

say "2a. MongoDB container"
if [[ "$(docker inspect -f '{{.State.Running}}' "$MONGO_CONTAINER" 2>/dev/null)" == "true" ]]; then
  ok "$MONGO_CONTAINER already running"
else
  docker rm -f "$MONGO_CONTAINER" >/dev/null 2>&1 || true
  # mongo:8.0 and mongo:latest will NOT boot on Docker Desktop's current kernel
  # (>=6.19, SERVER-121912) — the container exits instantly. 8.2 is fine.
  docker run -d --name "$MONGO_CONTAINER" --restart unless-stopped -p 27017:27017 \
    -e MONGO_INITDB_ROOT_USERNAME=root -e MONGO_INITDB_ROOT_PASSWORD="$MONGO_ROOT_PW" \
    "$MONGO_IMAGE" >/dev/null
  for _ in $(seq 1 40); do
    mongo_root --eval 'db.runCommand({ping:1}).ok' 2>/dev/null | grep -q '^1$' && break; sleep 1
  done
  ok "$MONGO_IMAGE up on 27017"
fi

say "2b. Convert the JSON to typed NDJSON"
# Pin the integers to Int32. Left as plain JSON numbers, MongoDB stores them as
# doubles and the connector then exposes BOTH `salary` and `salary|double`,
# because it refuses to silently merge two BSON types into one column.
python3 - "$CUSTOMERS_JSON" "$WORK/customers.ndjson" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
INTS = {"lifetime_value","order_count","support_tickets","satisfaction_score","points"}
def conv(o):
    return {k: (conv(v) if isinstance(v, dict)
                else {"$numberInt": str(v)} if k in INTS and isinstance(v, int) else v)
            for k, v in o.items()}
docs = json.load(open(src))
with open(dst, "w") as f:
    for d in docs: f.write(json.dumps(conv(d)) + "\n")
print(f"    {len(docs)} documents -> {dst}")
PY

say "2c. Import, index, and grant a read-only user"
docker cp "$WORK/customers.ndjson" "$MONGO_CONTAINER:/tmp/customers.ndjson" >/dev/null
docker exec "$MONGO_CONTAINER" mongoimport --quiet -u root -p "$MONGO_ROOT_PW" \
  --authenticationDatabase admin --db retail --collection customers --drop \
  --file /tmp/customers.ndjson
mongo_root --eval "
db = db.getSiblingDB('retail');
// The connector reads validators and indexes to sharpen schema inference,
// so these make the inferred tables better than a bare sample would.
db.customers.createIndex({customer_id:1},{name:'customer_id_unique',unique:true});
db.customers.createIndex({customer_segment:1,lifetime_value:-1},{name:'segment_ltv'});
db.customers.createIndex({'location.region':1},{name:'geo_idx'});
db.customers.createIndex({'loyalty.tier':1},{name:'tier_idx'});
db.getSiblingDB('admin').createUser({user:'$MONGO_READER', pwd:'$MONGO_READER_PW',
  roles:[{role:'read', db:'retail'}]});
" >/dev/null 2>&1 || mongo_root --eval "
db.getSiblingDB('admin').grantRolesToUser('$MONGO_READER',[{role:'read',db:'retail'}]);" >/dev/null

say "2d. Show the audience one document"
mongo_root --eval "printjson(db.getSiblingDB('retail').customers.findOne({},{_id:0}))"
COUNT=$(mongo_root --eval "print(db.getSiblingDB('retail').customers.countDocuments())" | tr -d '[:space:]')
ok "retail.customers holds $COUNT documents — nested objects, no flattening done"

say "STEP 2 DONE"
