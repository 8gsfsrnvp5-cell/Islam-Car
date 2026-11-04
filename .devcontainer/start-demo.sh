#!/usr/bin/env bash
# Islamic Car — запуск демо-стенда в GitHub Codespaces (или на любой машине с Docker).
#   bash .devcontainer/start-demo.sh            собрать и запустить, показать ссылки и вход
#   bash .devcontainer/start-demo.sh --status   только показать ссылки и вход
#
# Только тестовые данные: SMS и письма пишутся в журнал и никому не уходят, оплата — тестовая без денег,
# демо-карточки помечены «ДЕМО». Не использовать для реальных клиентов и их персональных данных.
# Пароли создаются случайно и остаются только внутри этого Codespace: файлы .env, .demo/ и demo-access.txt
# не попадают в git. Повторный запуск ничего не удаляет и не создаёт заново.
set -euo pipefail
cd "$(dirname "$0")/.."

STATE_DIR=.demo
OWNER_FILE="$STATE_DIR/owner.env"
ACCESS_FILE=demo-access.txt
ENV_MARK="# Создано .devcontainer/start-demo.sh — демо-стенд, только тестовые данные"

say() { printf '\n\033[1;32m== %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m!! %s\033[0m\n' "$*" >&2; }

show_access() {
  # В журналах проверок на GitHub (CI) пароль не печатается
  if [[ -n "${CI:-}" ]]; then grep -v 'пароль:' "$ACCESS_FILE"; else cat "$ACCESS_FILE"; fi
}

if [[ "${1:-}" == "--status" ]]; then
  if [[ -f "$ACCESS_FILE" ]]; then
    show_access
  else
    echo "Демо-стенд ещё запускается (первый раз — 5–10 минут). Когда всё будет готово, ссылки и вход"
    echo "появятся в терминале и в файле $ACCESS_FILE. Показать снова: bash .devcontainer/start-demo.sh --status"
  fi
  exit 0
fi

# --- адреса сайтов ---
if [[ -n "${CODESPACE_NAME:-}" ]]; then
  domain="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  CLIENT_URL="https://${CODESPACE_NAME}-3000.${domain}"
  ADMIN_URL="https://${CODESPACE_NAME}-3001.${domain}"
  COOKIE_SECURE=true
else
  CLIENT_URL="http://localhost:3000"
  ADMIN_URL="http://localhost:3001"
  COOKIE_SECURE=false
fi

random_hex() { od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'; }

# --- настройки (.env читает docker compose) ---
if [[ -f .env && "$(head -n 1 .env)" != "$ENV_MARK" ]]; then
  warn "Файл .env уже есть и создан не этим скриптом — не трогаю его. Для демо-стенда нужен отдельный Codespace."
  exit 1
fi
umask 077
pg_password=""
[[ -f .env ]] && pg_password="$(sed -n 's/^POSTGRES_PASSWORD=//p' .env)"
[[ -n "$pg_password" ]] || pg_password="$(random_hex 24)"
cat > .env <<EOF
$ENV_MARK
# Не коммитить. Пересоздаётся при каждом запуске, пароль базы сохраняется.
POSTGRES_PASSWORD=$pg_password
ENVIRONMENT=development
ALLOWED_ORIGINS=$CLIENT_URL,$ADMIN_URL
COOKIE_SECURE=$COOKIE_SECURE
PUBLIC_CLIENT_URL=$CLIENT_URL
CLIENT_PUBLIC_URL=$CLIENT_URL
# Тестовые режимы: сообщения только в журнал, оплата без денег
SMS_PROVIDER=log
EMAIL_PROVIDER=log
PAYMENT_PROVIDER=sandbox
EOF

# Вход владельца: из секретов Codespaces ISLAMCAR_DEMO_LOGIN / ISLAMCAR_DEMO_PASSWORD, иначе случайный.
# Запоминается при первом запуске.
mkdir -p "$STATE_DIR"
if [[ ! -f "$OWNER_FILE" ]]; then
  login="${ISLAMCAR_DEMO_LOGIN:-owner@demo.local}"
  password="${ISLAMCAR_DEMO_PASSWORD:-$(random_hex 4)-$(random_hex 4)-$(random_hex 4)}"
  printf 'OWNER_LOGIN=%q\nOWNER_PASSWORD=%q\n' "$login" "$password" > "$OWNER_FILE"
fi
# shellcheck source=/dev/null
source "$OWNER_FILE"

# --- запуск ---
say "Жду Docker"
for _ in $(seq 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
if ! docker info >/dev/null 2>&1; then
  warn "Docker не запустился. Перезапустите Codespace (Ctrl+Shift+P → «Codespaces: Rebuild Container»)."
  exit 1
fi

if docker image inspect islamcar-api >/dev/null 2>&1; then
  say "Запускаю сервисы"
else
  say "Первый запуск: собираю систему, это займёт 5–10 минут"
fi
docker compose up -d --build

wait_url() {  # адрес, предел в секундах
  local i
  for ((i = 0; i < $2; i += 3)); do
    curl -fsS -o /dev/null --max-time 5 "$1" 2>/dev/null && return 0
    sleep 3
  done
  return 1
}
say "Жду, пока сервисы ответят"
wait_url http://localhost:8000/api/health 240 || { warn "API не отвечает. Журнал: docker compose logs api"; exit 1; }
wait_url http://localhost:3000/ 180 || { warn "Сайт не отвечает. Журнал: docker compose logs client"; exit 1; }
wait_url http://localhost:3001/login 180 || { warn "Админка не отвечает. Журнал: docker compose logs admin"; exit 1; }

say "Учётная запись владельца"
if ! out="$(docker compose exec -T -e OWNER_PASSWORD="$OWNER_PASSWORD" api python -m scripts.create_owner \
    --login "$OWNER_LOGIN" --name "Демо-владелец" --password-env OWNER_PASSWORD 2>&1)"; then
  if [[ "$out" != *"уже существует"* ]]; then
    warn "Не удалось создать владельца: $out"
    exit 1
  fi
  out="Владелец уже создан ранее"
fi
echo "$out"

cars="$(docker compose exec -T api python -c '
from sqlalchemy import func, select
from app.db import SessionLocal
from app.models import Car
with SessionLocal() as db:
    print(db.scalar(select(func.count()).select_from(Car)))
' | tail -n 1)"
if [[ "$cars" == "0" ]]; then
  say "Демо-карточки автомобилей (помечены «ДЕМО», VIN не настоящие)"
  docker compose exec -T api python -m scripts.seed_demo
fi

# --- ссылки для всех (только в Codespaces) ---
http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$1" 2>/dev/null || true; }
public=""
if [[ -n "${CODESPACE_NAME:-}" ]]; then
  say "Открываю ссылки для всех"
  for _ in 1 2 3 4 5 6; do
    gh codespace ports visibility 3000:public 3001:public -c "$CODESPACE_NAME" >/dev/null 2>&1 || true
    sleep 5
    if [[ "$(http_code "$CLIENT_URL/")" == 200 && "$(http_code "$ADMIN_URL/login")" == 200 ]]; then
      public=1
      break
    fi
  done
fi

{
  echo "================ Islamic Car — демо-стенд (только тестовые данные) ================"
  echo
  echo "Сайт для покупателей: $CLIENT_URL"
  echo "Админка:              $ADMIN_URL"
  echo
  echo "Вход в админку:"
  echo "  логин:  $OWNER_LOGIN"
  echo "  пароль: $OWNER_PASSWORD"
  echo
  if [[ -n "${CODESPACE_NAME:-}" ]]; then
    if [[ -n "$public" ]]; then
      echo "Ссылки открыты для всех — их можно отправлять."
    else
      echo "Ссылки пока открываются только у вас. Чтобы открыть их для всех: внизу вкладка «Порты» (PORTS) →"
      echo "правой кнопкой по 3000 → «Видимость порта» (Port Visibility) → «Общедоступный» (Public), то же для 3001."
    fi
    echo
    echo "Стенд работает, пока включён этот Codespace. Если с ним никто не работает, GitHub его усыпляет"
    echo "(по умолчанию через 30 минут, можно до 4 часов: github.com/settings/codespaces → Default idle timeout)."
    echo "Разбудить: откройте его на github.com/codespaces — ссылки и данные останутся прежними."
  fi
  echo "SMS и письма никому не уходят — они в журнале: docker compose logs api worker"
  echo "Показать это снова: bash .devcontainer/start-demo.sh --status"
  echo "==================================================================================="
} > "$ACCESS_FILE"

echo
show_access
