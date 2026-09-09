FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por tesseract-ocr-eng tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /data \
    && chmod +x /app/start.sh \
    && python -m compileall -q app scripts

EXPOSE 8080

# O Railway já executa o healthcheck HTTP configurado para /health.
# Não duplicamos o healthcheck no Dockerfile para evitar conflito de inicialização.
CMD ["/app/start.sh"]
