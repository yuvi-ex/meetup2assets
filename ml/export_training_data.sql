SELECT "order_id", "discount", "quantity", "sales", "shipping_cost",
       "category", "sub_category", "market", "region", "ship_mode", "segment",
       CASE WHEN "profit" < 0 THEN 1 ELSE 0 END AS LOSS
FROM MONGO_SUPERSTORE."ORDERS"
