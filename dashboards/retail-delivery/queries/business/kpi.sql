-- Headline figures. Joined live: RETAIL.ORDERS (Exasol) x retail.customers (MongoDB).
SELECT COUNT(*) AS LINES_N,
       ROUND(SUM(g."REVENUE"),2)                               AS REVENUE_SUM,
       ROUND(AVG(g."REVENUE"),2)                               AS REVENUE_AVG,
       ROUND(SUM(g."LOST_REVENUE"),2)                          AS LOST_REVENUE_SUM,
       ROUND(AVG(g."LOST_REVENUE"),2)                          AS LOST_REVENUE_AVG,
       ROUND(SUM(g."NET_REVENUE"),2)                           AS NET_REVENUE_SUM,
       ROUND(AVG(g."NET_REVENUE"),2)                           AS NET_REVENUE_AVG,
       ROUND(SUM(g."QUANTITY"),2)                              AS QUANTITY_SUM,
       ROUND(AVG(g."QUANTITY"),2)                              AS QUANTITY_AVG,
       ROUND(100*AVG(g."RETURN_FLAG"),2)                                  AS RETURN_PCT,
       ROUND(100*SUM(g."GROSS_MARGIN")/NULLIF(SUM(g."REVENUE"),0),2)       AS MARGIN_PCT,
       ROUND(100*SUM(g."NET_REVENUE")/NULLIF(SUM(g."REVENUE"),0),2)        AS NET_PCT,
       ROUND(100*SUM(g."LOST_REVENUE")/NULLIF(SUM(g."REVENUE"),0),2)       AS LOST_PCT,
       ROUND(AVG(g."REVENUE"),2)                                          AS AVG_ORDER,
       ROUND(AVG(g."DISCOUNT_PCT"),2)                                     AS DISCOUNT_AVG,
       ROUND(AVG(g."RATING"),2)                                           AS RATING_AVG,
       ROUND(AVG(g."DELIVERY_DAYS"),2)                                    AS DELIVERY_DAYS_AVG,
       ROUND(100*AVG(g."BELOW_REORDER"),2)                                AS BELOW_REORDER_PCT,
       ROUND(AVG(g."STOCK_HEADROOM"),2)                                   AS STOCK_HEADROOM_AVG,
       COUNT(DISTINCT g."CUSTOMER_ID")                                    AS CUSTOMERS_N,
       COUNT(DISTINCT g."PRODUCT_ID")                                     AS PRODUCTS_N,
       MAX(g."ORDER_DATE") AS ASOF
  FROM "RETAIL"."ORDERS_ENRICHED" g
   WHERE ({f0!s} = '*' OR INSTR({f0!s}, '|' || TO_CHAR(g."ORDER_STATUS") || '|') > 0)
     AND ({f1!s} = '*' OR INSTR({f1!s}, '|' || TO_CHAR(g."STORE_NAME") || '|') > 0)
     AND ({f2!s} = '*' OR INSTR({f2!s}, '|' || TO_CHAR(g."CHANNEL") || '|') > 0)
     AND ({f3!s} = '*' OR INSTR({f3!s}, '|' || TO_CHAR(g."CATEGORY") || '|') > 0)
