# Запуск на Windows (PowerShell)

## Запуск двойным щелчком

1. Установите [Docker Desktop для Windows](https://docs.docker.com/desktop/setup/install/windows-install/),
   выберите Linux containers/WSL 2 и дождитесь запуска Docker.
2. Скачайте ZIP **ветки с исправлениями** из GitHub и полностью распакуйте его в папку,
   например `C:\Islam-Car`. Не запускайте файл изнутри ZIP.
3. Откройте **Start-Islam-Car.cmd**. Git, Python, Node.js и PostgreSQL отдельно устанавливать не требуется.
4. При первом запуске задайте логин, имя и пароль владельца. Пароль вводится скрыто, минимум 10 символов.
5. Откроются два окна браузера: админка `http://localhost:3001/login` и клиентский сайт `http://localhost:3000`.

Скрипт создаёт `.env` только при его отсутствии и генерирует случайный пароль базы. Существующие настройки
сохраняются. Учётная запись владельца повторно не создаётся. Порты доступны только этому компьютеру.
Внешние платежи, SMS и email в новой локальной конфигурации выключены.

**Stop-Islam-Car.cmd** останавливает контейнеры, сохраняя базу, загруженные файлы и резервные копии.
Для повторного запуска снова откройте **Start-Islam-Car.cmd**. Закрытие окна запуска не останавливает приложение.
Не удаляйте Docker volumes и не меняйте пароль существующей базы в `.env` произвольно.

### Как войти именно клиентом

Клиентская и административная учётные записи разные. Сначала в админке создайте реальные карточки клиента
и автомобиля, заполните продавца, подтвердите личность покупателя и оформите договор. После фактического
подписания договора нажмите **«Выдать доступ в кабинет»** в карточке клиента. Откройте полученную ссылку
активации на `http://localhost:3000`, задайте отдельный пароль клиента и войдите на `http://localhost:3000/login`
по телефону клиента. Клиент видит только свои документы, график и платежи.

Без оформленного договора доступ к личному кабинету не выдаётся. Каталог и подача заявки доступны
сразу. Фиктивные договоры и клиенты для обхода этого условия не создаются.

Если клиент должен открыть сайт с другого устройства, `localhost` не подойдёт: это адрес текущего
компьютера. Публикация сайта в интернете — отдельный шаг после выбора размещения.

Ниже — ручные способы запуска.

## Способ 1. Docker Desktop

Требуется: Docker Desktop с включённым WSL 2, Git.

```powershell
git clone https://github.com/8gsfsrnvp5-cell/Islam-Car.git
cd Islam-Car
Copy-Item .env.example .env
notepad .env                       # задайте длинный POSTGRES_PASSWORD
docker compose up -d --build       # первая сборка — несколько минут
docker compose ps                  # все пять сервисов должны быть в состоянии running
```

Создайте учётную запись владельца (пароль вводится скрыто, не короче 10 символов):

```powershell
docker compose exec api python -m scripts.create_owner --login owner@example.ru --name "Фамилия Имя"
```

- Админка: http://localhost:3001
- Сайт: http://localhost:3000
- Фоновый обработчик (напоминания, задачи, резервные копии) запускается сервисом `worker` автоматически.
- Документация API: http://localhost:8000/api/docs (отключается при `ENVIRONMENT=production`)

Остановка — `docker compose down`. Данные базы и фото сохраняются в томах `pgdata` и `storage`
и не удаляются при перезапуске. Полное удаление данных: `docker compose down -v` (необратимо).

## Способ 2. Без Docker

Требуется: Python 3.12+, Node.js 20.9+ (рекомендуется 22 или 24), PostgreSQL 15+.

### 1. База данных

В `psql` от имени администратора PostgreSQL:

```sql
CREATE USER islamcar WITH PASSWORD 'придумайте-пароль';
CREATE DATABASE islamcar OWNER islamcar;
CREATE DATABASE islamcar_test OWNER islamcar;  -- для автотестов
```

### 2. Сервер API

```powershell
cd services\api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
notepad .env                       # укажите пароль в DATABASE_URL
alembic upgrade head
python -m scripts.create_owner --login owner@example.ru --name "Фамилия Имя"
uvicorn app.main:app --port 8000
```

Фоновый обработчик — в отдельном окне PowerShell из той же папки:

```powershell
cd services\api
.\.venv\Scripts\Activate.ps1
python -m app.worker
```

Без обработчика сайт и админка работают, но напоминания, контроль сроков и резервные копии не выполняются —
это видно в «Центре уведомлений» → «Фоновый обработчик».

Если PowerShell запрещает запуск `Activate.ps1`, выполните один раз:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 3. Сайт и админка

В новом окне PowerShell, из корня репозитория:

```powershell
npm install
npm run dev:client                 # http://localhost:3000
```

И ещё в одном окне:

```powershell
npm run dev:admin                  # http://localhost:3001
```

Если API запущен не на `http://localhost:8000`, задайте адрес перед запуском: `$env:API_INTERNAL_URL = "http://адрес:порт"`.

## Проверки

```powershell
# API: линтер и интеграционные тесты (по умолчанию на SQLite в памяти)
cd services\api
.\.venv\Scripts\Activate.ps1
ruff check .
pytest

# Те же тесты на PostgreSQL (отдельная база с "test" в имени — рабочая база не используется)
$env:TEST_DATABASE_URL = "postgresql+psycopg://islamcar:пароль@localhost:5432/islamcar_test"
pytest
Remove-Item Env:TEST_DATABASE_URL

# Веб: тесты денежных функций, сборка и проверка типов
cd ..\..
npm run test:shared
npm run build
npm run typecheck
```

## Первые шаги после входа

1. **Настройки** → заполните продавца и реквизиты для оплаты; включите второй фактор входа.
2. **Реестр автомобилей** → добавьте автомобиль, укажите собственность, VIN, документ о покупке и цены → «Опубликовать».
3. Заявки с сайта появятся в разделе **Заявки клиентов** и в уведомлениях.
4. Из заявки создайте клиента → заполните реквизиты → «Подтвердить личность» → «Подготовить договор».
5. После подписания на бумаге зафиксируйте подписание в карточке договора и выдайте клиенту доступ в кабинет.
6. Поступления подтверждайте в карточке договора по банковской выписке.

### Каналы уведомлений и резервные копии без Docker

В `services/api/.env`:

```
# тестовый режим: сообщения пишутся в журнал, наружу не уходят (запрещён при ENVIRONMENT=production)
SMS_PROVIDER=log
EMAIL_PROVIDER=log
# или реальная почта
# EMAIL_PROVIDER=smtp
# SMTP_HOST=smtp.example.ru
# SMTP_FROM=noreply@example.ru
BACKUP_DIR=D:/IslamicCar/backups
PG_DUMP_PATH="C:/Program Files/PostgreSQL/17/bin/pg_dump.exe"
PG_RESTORE_PATH="C:/Program Files/PostgreSQL/17/bin/pg_restore.exe"
```

Версия `pg_dump` должна быть не ниже версии сервера PostgreSQL.

### Онлайн-оплата и помощник локально

```
# тестовая онлайн-оплата без денег (запрещена при ENVIRONMENT=production)
PAYMENT_PROVIDER=sandbox
# помощник по нормам: ключ Claude API; включает владелец в «Пользователи и настройки»
# ANTHROPIC_API_KEY=...
```

Демо-карточки автомобилей для локальной разработки: `python -m scripts.seed_demo`
(работает только при `ENVIRONMENT=development`, карточки помечены «ДЕМО»).
