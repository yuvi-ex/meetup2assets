#!/usr/bin/env bash
# STEP 5 — the payoff. One SQL statement, two engines, an answer the CRM denies.
source "$(dirname "$0")/lib/common.sh"

say "Q1. Which customer segment and loyalty tier generate the most revenue?"
xsql -c "
SELECT c.\"customer_segment\"                   AS SEGMENT,
       l.\"tier\"                               AS TIER,
       COUNT(DISTINCT c.\"customer_id\")        AS CUSTOMERS,
       ROUND(SUM(o.REVENUE),0)                  AS REVENUE,
       ROUND(SUM(o.REVENUE)/COUNT(DISTINCT c.\"customer_id\"),0) AS REV_PER_CUSTOMER,
       ROUND(AVG(o.RATING),2)                   AS AVG_RATING,
       ROUND(100*AVG(o.RETURN_FLAG),1)          AS RETURN_PCT
FROM RETAIL.ORDERS o                                  -- Exasol table, 2,500 rows
JOIN MONGO_RETAIL.\"CUSTOMERS\" c                     -- MongoDB, live
       ON c.\"customer_id\" = o.CUSTOMER_ID
JOIN MONGO_RETAIL.\"CUSTOMERS_loyalty\" l             -- the EMBEDDED loyalty object
       ON l.\"_id\" = c.\"loyalty|object\"
GROUP BY 1,2 ORDER BY REVENUE DESC;" | xtable

cat <<'NOTE'

    Premium/Gold earns the most revenue -- but only because it holds the most
    customers. Revenue PER customer is within 0.3% across all three tiers, and
    ratings and returns do not follow either.
NOTE

say "Q2. So is the CRM's own lifetime_value telling the truth?"
xsql -c "
SELECT c.\"customer_segment\"                            AS SEGMENT,
       ROUND(AVG(c.\"lifetime_value\"),0)                AS MONGO_SAYS_LTV,
       ROUND(AVG(c.\"order_count\"),1)                   AS MONGO_SAYS_ORDERS,
       ROUND(SUM(o.REVENUE)/COUNT(DISTINCT c.\"customer_id\"),0) AS EXASOL_SAYS_REVENUE,
       ROUND(COUNT(*)/COUNT(DISTINCT c.\"customer_id\"),1)       AS EXASOL_SAYS_ORDERS
FROM RETAIL.ORDERS o
JOIN MONGO_RETAIL.\"CUSTOMERS\" c ON c.\"customer_id\" = o.CUSTOMER_ID
GROUP BY 1 ORDER BY MONGO_SAYS_LTV DESC;" | xtable

cat <<'NOTE'

    The customer document claims a 6x value spread and ~19 orders each.
    The order facts show a 0.3% spread and exactly 10 orders each.
    Neither system could have told you that on its own. THIS is the reason
    the join has to happen at query time, on live data.
NOTE

say "Q3. And nothing was copied — here is the plan"
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
