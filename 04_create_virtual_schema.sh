#!/usr/bin/env bash
# STEP 4 — the moment worth showing: two SQL statements and MongoDB is queryable.
source "$(dirname "$0")/lib/common.sh"

say "4a. Register the MongoDB deployment as an Exasol CONNECTION"
# HOST_GATEWAY, not 127.0.0.1: this string is dialled from inside the Exasol VM.
# Credentials live in the connection object; they never appear in a query plan.
xsql -c "
CREATE OR REPLACE CONNECTION MONGODB_RETAIL
TO 'mongodb://$HOST_GATEWAY:27017/?authSource=admin&directConnection=true'
USER '$MONGO_READER' IDENTIFIED BY '$MONGO_READER_PW';" >/dev/null
ok "CONNECTION MONGODB_RETAIL"

say "4b. Create the virtual schema — no DDL, no column list, no copy"
xsql -c "
DROP VIRTUAL SCHEMA IF EXISTS MONGO_RETAIL CASCADE;
CREATE VIRTUAL SCHEMA MONGO_RETAIL
USING MONGODB_VS.MONGODB_ADAPTER WITH
  MONGODB_CONNECTION='MONGODB_RETAIL'
  DATABASE='retail'
  COLLECTION='customers';" >/dev/null
ok "VIRTUAL SCHEMA MONGO_RETAIL"

say "4c. What did it infer? (this is the slide that lands)"
xsql -c "SELECT COLUMN_TABLE AS \"TABLE\", COLUMN_NAME, COLUMN_TYPE
         FROM EXA_ALL_COLUMNS WHERE COLUMN_SCHEMA='MONGO_RETAIL'
           AND COLUMN_NAME NOT LIKE '%|empty' AND COLUMN_NAME <> '__mongodb_source_json'
         ORDER BY COLUMN_TABLE, COLUMN_ORDINAL_POSITION;" | xtable

cat <<'NOTE'

    One collection became four tables:
      CUSTOMERS               the root document
      CUSTOMERS_location      the embedded location object
      CUSTOMERS_loyalty       the embedded loyalty object
      CUSTOMERS_preferences   the embedded preferences object
    Column-name conventions the audience will ask about:
      x|object   foreign key to that child table's _id
      x|array    the element COUNT (the elements live in an _arr child table)
      x|empty    empty string, kept distinct from a missing field
      x|n        an explicit JSON null, kept distinct from absent
NOTE

say "4d. Prove it is live, not a copy"
xsql -c "SELECT COUNT(*) AS DOCS_SEEN_FROM_SQL FROM MONGO_RETAIL.\"CUSTOMERS\";" | xtable

say "STEP 4 DONE"
