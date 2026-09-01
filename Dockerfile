FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data && chmod +x /app/start.sh \
    && python -m compileall -q app scripts

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python - <<'PY'
import os, urllib.request
urllib.request.urlopen(f"http://127.0.0.1:{os.getenv('PORT','8080')}/health", timeout=3).read()
PY
CMD ["/app/start.sh"]
