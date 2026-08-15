FROM python:3.11-slim

ARG TDM_COMMIT_SHA=unknown

WORKDIR /app

RUN pip install --no-cache-dir "aiohttp>=3.9,<4.0" truststore

COPY . .

# Create a non-root user
RUN useradd --create-home --shell /bin/bash app \
    && mkdir -p /app/data \
    && chown -R app:app /app
USER app

ENV TDM_DATA_DIR=/app/data \
    TDM_COMMIT_SHA=$TDM_COMMIT_SHA \
    TDM_ENGLISH_ONLY=1 \
    PYTHONUNBUFFERED=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/state', timeout=3)" || exit 1

CMD ["python", "main.py", "--headless", "-vv"]
