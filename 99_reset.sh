#!/usr/bin/env bash
# Put the machine back to "before the demo" — keeps the adapter and the Rust SLC,
# drops only what steps 2, 2b and 6 created, so a re-run starts from step 2.
#
# IT USED TO MISS HALF OF ITS OWN JOB. Step 2b builds a SECOND stack — the
# `superstore` MongoDB database, the MONGODB_SUPERSTORE connection and the
# MONGO_SUPERSTORE virtual schema — and none of it was dropped here. A "reset"
# left them behind, so the next run re-imported 51,290 documents on top of the
# old ones and step 7 trained on whatever that produced.
source "$(dirname "$0")/lib/common.sh"

say "Dropping Exasol objects (steps 2, 2b, 4, 5)"
# CASCADE on the virtual schemas takes the views built over them with it. Order
# matters: a CONNECTION cannot be dropped while a virtual schema still uses it.
xsql -c "DROP VIRTUAL SCHEMA IF EXISTS MONGO_RETAIL CASCADE;
         DROP VIRTUAL SCHEMA IF EXISTS MONGO_SUPERSTORE CASCADE;
         DROP SCHEMA IF EXISTS RETAIL CASCADE;
         DROP CONNECTION IF EXISTS MONGODB_RETAIL;
         DROP CONNECTION IF EXISTS MONGODB_SUPERSTORE;" >/dev/null \
  && ok "virtual schemas, RETAIL and both connections dropped"

say "Dropping the MongoDB data"
# The whole `superstore` database, not just the collection: 02b also grants the
# reader role on it, and dropping the database clears the lot.
mongo_root --eval "db.getSiblingDB('retail').customers.drop()" >/dev/null \
  && ok "retail.customers dropped"
mongo_root --eval "db.getSiblingDB('superstore').dropDatabase()" >/dev/null \
  && ok "superstore database dropped"

say "Local artifacts from the Superstore load"
# 02b unpacks a 36 MB JSON and writes an ndjson beside it; both are regenerable.
rm -f "$WORK/StoreSales.json" "$WORK/superstore.ndjson" && ok "work files removed"

warn "left in place: the Rust SLC, MONGODB_VS scripts, the .so in BucketFS,"
warn "               the deployed dashboards, and step 7's ML schema"
warn "               (./99_reset_ml.sh for that, ./98_teardown.sh for everything)"
