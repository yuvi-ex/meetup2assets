#!/usr/bin/env python3
"""Train the order-line loss model that Exasol will run as a UDF.

The training rows come out of MongoDB — pulled through the virtual schema by
export_training_data.sql — and the model goes back into the database as a
pickle in BucketFS. Nothing about this file knows it is talking to MongoDB.

Run it through the pinned container, never the host:
    docker run --rm -v "$PWD:/work" exasol-ml-train python train.py
"""
import json
import time

import joblib
import numpy
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

# What we ask of every order line: is this one going to lose money?
TARGET = "profit < 0 (the order line loses money)"

# Deliberately no profit, no cost, no margin among the features — those are the
# answer. Only what is knowable when the line is placed.
NUMERIC = ["discount", "quantity", "sales", "shipping_cost"]
CATEGORICAL = ["category", "sub_category", "market", "region", "ship_mode", "segment"]

print("1/5  reading training rows exported from MongoDB")
df = pd.read_csv("/work/superstore_train.csv")
print(f"     {len(df):,} order lines · {df['LOSS'].mean():.1%} of them lost money")

print("2/5  splitting 75 / 25, stratified on the target")
X, y = df[NUMERIC + CATEGORICAL], df["LOSS"]
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=7, stratify=y)
print(f"     train {len(X_train):,}   holdout {len(X_test):,}")

print("3/5  fitting  one-hot -> gradient boosting")
model = Pipeline([
    # sparse_output=False: HistGradientBoosting refuses a sparse X.
    ("prep", ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL)],
        remainder="passthrough")),
    ("clf", HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=7)),
])
started = time.time()
model.fit(X_train, y_train)
print(f"     fitted in {time.time() - started:.1f}s")

print("4/5  scoring the holdout the model has never seen")
probability = model.predict_proba(X_test)[:, 1]
auc = roc_auc_score(y_test, probability)
ap = average_precision_score(y_test, probability)
print(f"     ROC AUC {auc:.4f}   average precision {ap:.4f}   base rate {y.mean():.4f}")

print("5/5  writing the artifact Exasol will load")
joblib.dump(model, "/work/loss_model.pkl", compress=3)
card = {
    "target": TARGET,
    "features_numeric": NUMERIC,
    "features_categorical": CATEGORICAL,
    "rows_total": int(len(df)), "rows_train": int(len(X_train)), "rows_test": int(len(X_test)),
    "base_rate": round(float(y.mean()), 4),
    "roc_auc": round(float(auc), 4),
    "avg_precision": round(float(ap), 4),
    # Recorded so a future reader can tell whether this pickle will still load.
    "sklearn": sklearn.__version__, "numpy": numpy.__version__,
    "pandas": pd.__version__, "joblib": joblib.__version__,
}
json.dump(card, open("/work/loss_model.meta.json", "w"), indent=2)
print("     loss_model.pkl + loss_model.meta.json written to /work")
