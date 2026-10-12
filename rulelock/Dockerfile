# One image, one Flask process: c1 imports c2, c3 and c4. Build context = the rulelock/ folder.
#   docker build -t rulelock ./rulelock
FROM python:3.11-slim
WORKDIR /app
ENV APP_ENV=production PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=5001

# dependencies of all four folders live in c1's requirements.txt (scikit-learn is c3's, Flask is shared)
COPY c1-data-collection/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY c1-data-collection ./c1-data-collection
COPY c2-rule-engine ./c2-rule-engine
COPY c3-anomaly-detection ./c3-anomaly-detection
COPY c4-enforcement-engine ./c4-enforcement-engine

# train the anomaly model at build time (no model file is stored in the repo)
RUN cd c3-anomaly-detection && python train_model.py

RUN addgroup --system rulelock && adduser --system --ingroup rulelock rulelock
USER rulelock
WORKDIR /app/c1-data-collection
EXPOSE 5001
# Render free has about 512 MB RAM: 1 worker with 4 threads (WEB_CONCURRENCY=2 at most)
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5001} --workers ${WEB_CONCURRENCY:-1} --threads 4 --timeout 60 --preload app:app"]
