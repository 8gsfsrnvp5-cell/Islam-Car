FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

RUN useradd --create-home --uid 1000 islamcar && mkdir -p /data/storage && chown -R islamcar /data
USER islamcar

ENV STORAGE_DIR=/data/storage
EXPOSE 8000

# Миграции применяются при каждом старте: идемпотентно и не трогает существующие данные
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
