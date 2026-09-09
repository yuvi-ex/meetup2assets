#!/usr/bin/env bash
# STEP 5 — the payoff. One SQL statement, two engines, an answer the CRM denies.
# Narration: "customer information in MongoDB, transactions in Exasol".
#
# Every column is aliased MONGO_* or EXASOL_* on purpose. The presenter cannot
# point at the screen mid-sentence, so the column name has to say which engine
# the value came from. Do not "tidy" those prefixes away.
source "$(dirname "$0")/lib/common.sh"

ask <<'Q'
Show me the transactions AND the customer details for our Premium / Gold segment.

  MongoDB holds WHO THEY ARE   — name, segment, loyalty tier, city
  Exasol  holds WHAT THEY DID  — 2,500 transactions, revenue, products

  The WHERE clause filters on MongoDB fields. The ORDER BY sorts an Exasol one.
Q
say "Q1. Premium/Gold — one row per transaction, customer details attached"
xsql -c "
SELECT o.ORDER_ID            AS \"EXASOL_ORDER_ID\",
       o.ORDER_DATE          AS \"EXASOL_ORDER_DATE\",
       o.PRODUCT_NAME        AS \"EXASOL_PRODUCT\",
       o.REVENUE             AS \"EXASOL_REVENUE\",
       c.\"name\"              AS \"MONGO_NAME\",
       l.\"tier\"              AS \"MONGO_TIER\",
       loc.\"city\"            AS \"MONGO_CITY\"
FROM RETAIL.ORDERS o                                    -- Exasol table, 2,500 rows
JOIN MONGO_RETAIL.\"CUSTOMERS\" c                         -- MongoDB, live
       ON c.\"customer_id\" = o.CUSTOMER_ID
JOIN MONGO_RETAIL.\"CUSTOMERS_loyalty\" l                 -- the EMBEDDED loyalty object
       ON l.\"_id\" = c.\"loyalty|object\"
JOIN MONGO_RETAIL.\"CUSTOMERS_location\" loc              -- the EMBEDDED location object
       ON loc.\"_id\" = c.\"location|object\"
WHERE c.\"customer_segment\" = 'Premium' AND l.\"tier\" = 'Gold'
ORDER BY o.REVENUE DESC LIMIT 10;" | xtable

cat <<'NOTE'

    The name, tier and city were never loaded into Exasol. They were fetched
    from MongoDB while this query ran.
    Honest caveat: the top rows repeat one product at one price -- this retail
    set is generated. The mechanism is real; the product mix is not.
NOTE

ask <<'Q'
Who are our top 10 customers by what they ACTUALLY spent?
And does the CRM's lifetime_value agree?

  MongoDB says  lifetime_value, tier   — what the CRM BELIEVES
  Exasol  says  SUM(revenue)           — what the TRANSACTIONS show
Q
say "Q2. Top 10 customers by real spend, next to the CRM's opinion"
xsql -c "
SELECT c.\"customer_id\"      AS \"MONGO_ID\",
       c.\"name\"             AS \"MONGO_NAME\",
       loc.\"city\"           AS \"MONGO_CITY\",
       l.\"tier\"             AS \"MONGO_TIER\",
       c.\"lifetime_value\"   AS \"MONGO_CRM_LTV\",
       COUNT(*)                AS \"EXASOL_ORDERS\",
       ROUND(SUM(o.REVENUE),0) AS \"EXASOL_SPEND\"
FROM RETAIL.ORDERS o
JOIN MONGO_RETAIL.\"CUSTOMERS\" c            ON c.\"customer_id\" = o.CUSTOMER_ID
JOIN MONGO_RETAIL.\"CUSTOMERS_loyalty\" l    ON l.\"_id\" = c.\"loyalty|object\"
JOIN MONGO_RETAIL.\"CUSTOMERS_location\" loc ON loc.\"_id\" = c.\"location|object\"
GROUP BY 1,2,3,4,5
ORDER BY \"EXASOL_SPEND\" DESC LIMIT 10;" | xtable

cat <<'NOTE'

    The top three spent IDENTICALLY -- 128,970 each -- and the CRM files them
    as Bronze, Gold and Silver, worth 19,528 / 68,498 / 32,468.
    C0046 is our 5th-best customer; the CRM values him at 3,658, the lowest
    number on the page. Tier is assigned in MongoDB, money is counted in
    Exasol, and nothing had ever compared the two.
NOTE

ask <<'Q'
Which city and which category actually earn the money?

  MongoDB holds the city — nested INSIDE the customer document
  Exasol  holds the category and the revenue
Q
say "Q3. Revenue by city and category"
xsql -c "
SELECT loc.\"city\"            AS \"MONGO_CITY\",
       loc.\"region\"          AS \"MONGO_REGION\",
       o.CATEGORY                   AS \"EXASOL_CATEGORY\",
       COUNT(*)                     AS \"EXASOL_ORDERS\",
       ROUND(SUM(o.REVENUE),0)      AS \"EXASOL_REVENUE\",
       ROUND(AVG(o.DISCOUNT_PCT),1) AS \"EXASOL_AVG_DISCOUNT\"
FROM RETAIL.ORDERS o
JOIN MONGO_RETAIL.\"CUSTOMERS\" c            ON c.\"customer_id\" = o.CUSTOMER_ID
JOIN MONGO_RETAIL.\"CUSTOMERS_location\" loc ON loc.\"_id\" = c.\"location|object\"
GROUP BY 1,2,3
ORDER BY \"EXASOL_REVENUE\" DESC LIMIT 10;" | xtable

cat <<'NOTE'

    Order counts are near-identical (62-64). The whole revenue gap is discount.
    Say this BEFORE the room does: that discount column is a perfect ladder,
    0/5/10/15/20 per city, because this retail set is generated and discount
    was assigned by city. The genuine discount->loss signal is in the
    Superstore data the model trains on in step 7.
NOTE

# Optional closer. Skip it if the room is already convinced -- but it is the
# answer to the one hostile question a virtual schema always attracts.
ask <<'Q'
Fair question from the room: did Exasol just copy MongoDB overnight?
No. Watch what it sends to MongoDB when we filter.
Q
say "Q4. Nothing was copied — here is the plan"
xsql -c "EXPLAIN VIRTUAL SELECT \"customer_id\", \"customer_segment\"
         FROM MONGO_RETAIL.\"CUSTOMERS\" WHERE \"customer_segment\" = 'Premium' LIMIT 5;" \
  | jq -r '.statements[0].rows[0][1]' \
  | python3 -c "
import re, sys
plan = sys.stdin.read()
m = re.search(r'\"pushdown\":\{.*?\}\}', plan)
print('    predicate handed to MongoDB:')
print('      ' + (m.group(0) if m else '(none)'))
print('    credentials in the plan:', 'NONE — only the connection name' if 'reader-pass' not in plan else 'LEAKED')
"

say "STEP 5 DONE"
