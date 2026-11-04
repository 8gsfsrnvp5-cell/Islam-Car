# Образ для API и фонового обработчика. Контекст сборки — корень репозитория (нужны templates/contracts).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Шрифт с кириллицей для PDF и pg_dump/pg_restore 17 (версия как у сервера PostgreSQL в docker-compose)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg fonts-dejavu-core \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
 && apt-get purge -y curl gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/api/requirements.txt .
RUN pip install -r requirements.txt

COPY services/api/app ./app
COPY services/api/alembic ./alembic
COPY services/api/alembic.ini ./
COPY services/api/scripts ./scripts
COPY templates/contracts ./templates/contracts
COPY knowledge ./knowledge

RUN useradd --create-home --uid 1000 islamcar && mkdir -p /data/storage /backups && chown -R islamcar /data /backups
USER islamcar

ENV STORAGE_DIR=/data/storage \
    TEMPLATES_DIR=/app/templates/contracts \
    KNOWLEDGE_DIR=/app/knowledge
EXPOSE 8000

# Миграции применяются при каждом старте API: идемпотентно и не трогает существующие данные
CMD ["sh", "-c", "if [ \"${RUN_MIGRATIONS:-true}\" = true ]; then alembic upgrade head || exit 1; fi; exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS:-127.0.0.1}"]
