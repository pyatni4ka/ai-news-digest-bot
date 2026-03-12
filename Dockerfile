FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY digest_bot/ digest_bot/
COPY config/ config/

RUN pip install --no-cache-dir .

RUN mkdir -p /app/data/media

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/app/data/digest.db
ENV MEDIA_DIR=/app/data/media

CMD ["ai-news-digest", "bot"]
