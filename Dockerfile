FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data
WORKDIR /app

COPY app-source.zip /tmp/app-source.zip
RUN python -m zipfile -e /tmp/app-source.zip /app && rm /tmp/app-source.zip
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /data && chmod +x /app/start.sh
RUN python -m compileall -q app migrations scripts tests && python -m unittest discover -s tests -p 'test_*.py' -q

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 CMD ["python", "scripts/container_healthcheck.py"]
CMD ["/app/start.sh"]
