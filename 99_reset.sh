#!/usr/bin/env bash
# Put the machine back to "before the demo" — keeps the adapter and the Rust SLC,
# drops only what steps 2-6 created, so a re-run starts from step 2.
source "$(dirname "$0")/lib/common.sh"
say "Dropping Exasol objects"
xsql -c "DROP VIRTUAL SCHEMA IF EXISTS MONGO_RETAIL CASCADE;
         DROP SCHEMA IF EXISTS RETAIL CASCADE;
         DROP CONNECTION IF EXISTS MONGODB_RETAIL;" >/dev/null && ok "dropped"
say "Dropping the MongoDB collection"
mongo_root --eval "db.getSiblingDB('retail').customers.drop()" >/dev/null && ok "dropped"
warn "left in place: the Rust SLC, MONGODB_VS scripts, the .so in BucketFS, the dashboards"
