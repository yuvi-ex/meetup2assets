-- The join, as a view. Exasol facts x MongoDB customer documents, resolved live
-- on every query. Nothing is materialised.
CREATE OR REPLACE VIEW RETAIL.ORDERS_ENRICHED AS
SELECT o.ORDER_ID, o.ORDER_DATE, TO_CHAR(o.ORDER_DATE,'YYYY-MM') AS ORDER_MONTH,
       o.CUSTOMER_ID, o.STORE_ID, o.STORE_NAME, o.REGION AS STORE_REGION,
       o.PRODUCT_ID, o.PRODUCT_NAME, o.CATEGORY, o.SUBCATEGORY,
       o.QUANTITY, o.UNIT_PRICE, o.DISCOUNT_PCT, o.REVENUE, o.COST, o.GROSS_MARGIN,
       o.PAYMENT_METHOD, o.CHANNEL, o.ORDER_STATUS, o.DELIVERY_DAYS,
       o.INVENTORY_ON_HAND, o.REORDER_LEVEL, o.SELLER_ID, o.RATING, o.RETURN_FLAG,
       CASE WHEN o.ORDER_STATUS IN ('Cancelled','Returned') THEN o.REVENUE ELSE 0 END AS LOST_REVENUE,
       CASE WHEN o.ORDER_STATUS IN ('Delivered','Shipped')  THEN o.REVENUE ELSE 0 END AS NET_REVENUE,
       CASE WHEN o.INVENTORY_ON_HAND <= o.REORDER_LEVEL THEN 1 ELSE 0 END            AS BELOW_REORDER,
       o.INVENTORY_ON_HAND - o.REORDER_LEVEL                                        AS STOCK_HEADROOM,
       c."customer_segment" AS CUSTOMER_SEGMENT, c."age_band" AS AGE_BAND,
       c."lifetime_value" AS STATED_LTV, c."satisfaction_score" AS SATISFACTION,
       c."support_tickets" AS SUPPORT_TICKETS,
       lo."city" AS CUSTOMER_CITY, lo."state" AS CUSTOMER_STATE, lo."region" AS CUSTOMER_REGION,
       ly."tier" AS LOYALTY_TIER, ly."points" AS LOYALTY_POINTS,
       CASE WHEN ly."member" THEN 'member' ELSE 'non-member' END AS LOYALTY_MEMBER,
       p."favorite_category" AS FAV_CATEGORY, p."preferred_channel" AS PREF_CHANNEL,
       CASE WHEN p."marketing_opt_in" THEN 'opted in' ELSE 'opted out' END AS MARKETING_OPT_IN
FROM RETAIL.ORDERS o
JOIN MONGO_RETAIL."CUSTOMERS" c              ON c."customer_id" = o.CUSTOMER_ID
JOIN MONGO_RETAIL."CUSTOMERS_location" lo    ON lo."_id" = c."location|object"
JOIN MONGO_RETAIL."CUSTOMERS_loyalty" ly     ON ly."_id" = c."loyalty|object"
JOIN MONGO_RETAIL."CUSTOMERS_preferences" p  ON p."_id"  = c."preferences|object";
GRANT SELECT ON SCHEMA RETAIL TO mcp_readonly;
