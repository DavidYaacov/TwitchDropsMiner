FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create a non-root user
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Default environment variables
ENV CRON_SCHEDULE=30
ENV EXCLUDE=
ENV PROXY=
ENV PRIORITY=
ENV PRIORITY_MODE=PRIORITY_ONLY

CMD ["python", "headless_main.py"]