WITH scored AS (
  SELECT ORDER_ID AS ROW_KEY, LOSS_PROB FROM (
    SELECT ML.PREDICT_LOSS(
             TO_CHAR(s."row_id"), s."discount", s."quantity", s."sales", s."shipping_cost",
             s."category", s."sub_category", s."market", s."region", s."ship_mode", s."segment")
    FROM MONGO_SUPERSTORE."ORDERS" s)
),
actual AS (
  SELECT TO_CHAR(s."row_id") AS ROW_KEY, s."profit" AS PROFIT, s."sales" AS SALES
  FROM MONGO_SUPERSTORE."ORDERS" s
)
SELECT CASE WHEN sc.LOSS_PROB >= 0.9 THEN '4 flagged >=0.90'
            WHEN sc.LOSS_PROB >= 0.5 THEN '3 0.50-0.89'
            WHEN sc.LOSS_PROB >= 0.1 THEN '2 0.10-0.49'
            ELSE '1 below 0.10' END                       AS RISK_BAND,
       COUNT(*)                                           AS LINES,
       ROUND(100*AVG(CASE WHEN a.PROFIT < 0 THEN 1 ELSE 0 END),1) AS ACTUAL_LOSS_PCT,
       ROUND(SUM(a.SALES),0)                              AS SALES,
       ROUND(SUM(CASE WHEN a.PROFIT < 0 THEN a.PROFIT ELSE 0 END),0) AS LOSS_AMOUNT
FROM scored sc JOIN actual a ON a.ROW_KEY = sc.ROW_KEY
GROUP BY 1 ORDER BY 1;
