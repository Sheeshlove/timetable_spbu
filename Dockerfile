FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/app/data/bot.sqlite3

WORKDIR /app

# tzdata нужен zoneinfo для часовых поясов рассылки
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY scripts ./scripts

RUN useradd --system --uid 10001 --create-home botuser \
    && mkdir -p /app/data \
    && chown -R botuser:botuser /app
USER botuser

CMD ["python", "-m", "bot"]
