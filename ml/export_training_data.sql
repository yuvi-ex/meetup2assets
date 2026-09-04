SELECT "order_id", "discount", "quantity", "sales", "shipping_cost",
       "category", "sub_category", "market", "region", "ship_mode", "segment",
       CASE WHEN "profit" < 0 THEN 1 ELSE 0 END AS LOSS
FROM MONGO_SUPERSTORE."ORDERS"
-- ORDER BY is NOT cosmetic here. The virtual schema returns rows in whatever
-- order the MongoDB scan yields, and train_test_split shuffles BY POSITION, so
-- an unordered export gives a different train/test split on every run: observed
-- ROC AUC 0.9792 / 0.9796 / 0.9802 across three runs of the same data and the
-- same random_state. Sorting on the primary key makes the metric reproducible,
-- which is what lets the runsheet quote a number.
ORDER BY "row_id"
