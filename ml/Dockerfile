# Pinned to EXACTLY what the Exasol Python SLC ships, so the pickle this
# container produces loads inside the database. Check with ML.PROBE:
#   python 3.12.3 · numpy 1.26.4 · pandas 2.3.2 · scipy 1.16.2
#   scikit-learn 1.7.2 · joblib 1.5.3
FROM python:3.12-slim
RUN pip install --no-cache-dir \
      numpy==1.26.4 pandas==2.3.2 scipy==1.16.2 \
      scikit-learn==1.7.2 joblib==1.5.3
WORKDIR /work
