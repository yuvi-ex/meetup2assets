#!/usr/bin/env bash
# STEP 3 — Exasol side: 2,500 order lines as an ordinary relational table.
source "$(dirname "$0")/lib/common.sh"

say "3a. Normalise the CSV"
# Two things bite here every time:
#   - a CRLF file puts a trailing \r inside the LAST column, so `= 'Delivered'`
#     matches nothing while every row count still looks right;
#   - exapump matches the header to column names, so uppercase it.
{ head -1 "$ORDERS_CSV" | tr 'a-z' 'A-Z'; tail -n +2 "$ORDERS_CSV" | tr -d '\r'; } > "$WORK/orders.csv"
ok "$(( $(wc -l < "$WORK/orders.csv") - 1 )) rows, LF endings, uppercase header"

say "3b. Create the table with real types"
xsql -c "
CREATE SCHEMA IF NOT EXISTS RETAIL;
CREATE OR REPLACE TABLE RETAIL.ORDERS (
  ORDER_ID VARCHAR(10) NOT NULL, CUSTOMER_ID VARCHAR(10) NOT NULL, ORDER_DATE DATE NOT NULL,
  STORE_ID VARCHAR(10) NOT NULL, STORE_NAME VARCHAR(50) NOT NULL, REGION VARCHAR(20) NOT NULL,
  PRODUCT_ID VARCHAR(10) NOT NULL, PRODUCT_NAME VARCHAR(60) NOT NULL,
  CATEGORY VARCHAR(30) NOT NULL, SUBCATEGORY VARCHAR(30) NOT NULL,
  QUANTITY DECIMAL(3,0) NOT NULL, UNIT_PRICE DECIMAL(10,2) NOT NULL, DISCOUNT_PCT DECIMAL(5,2) NOT NULL,
  REVENUE DECIMAL(12,2) NOT NULL, COST DECIMAL(12,2) NOT NULL, GROSS_MARGIN DECIMAL(12,2) NOT NULL,
  PAYMENT_METHOD VARCHAR(20) NOT NULL, CHANNEL VARCHAR(20) NOT NULL, ORDER_STATUS VARCHAR(20) NOT NULL,
  DELIVERY_DAYS DECIMAL(3,0),   -- NULL for Cancelled and Processing: structural, not dirty
  INVENTORY_ON_HAND DECIMAL(5,0) NOT NULL, REORDER_LEVEL DECIMAL(5,0) NOT NULL,
  SELLER_ID VARCHAR(12) NOT NULL, RATING DECIMAL(2,0) NOT NULL, RETURN_FLAG DECIMAL(1,0) NOT NULL,
  CONSTRAINT PK_RETAIL_ORDERS PRIMARY KEY (ORDER_ID)
);
GRANT SELECT ON SCHEMA RETAIL TO mcp_readonly;" >/dev/null
ok "RETAIL.ORDERS created"

say "3c. Bulk load"
exapump upload -p starter-kit --table RETAIL.ORDERS "$WORK/orders.csv"

xsql -c "SELECT COUNT(*) AS ROWS_LOADED, COUNT(DISTINCT CUSTOMER_ID) AS CUSTOMERS,
                MIN(ORDER_DATE) AS FROM_DAY, MAX(ORDER_DATE) AS TO_DAY,
                COUNT(DELIVERY_DAYS) AS DELIVERY_DAYS_PRESENT
         FROM RETAIL.ORDERS;" | xtable

say "STEP 3 DONE — facts in Exasol, customers in MongoDB, nothing copied between them"
