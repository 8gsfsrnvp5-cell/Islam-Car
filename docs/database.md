# Схема базы данных

PostgreSQL, миграции Alembic (`services/api/alembic/versions`). Модели — `services/api/app/models.py`.

Общие правила:

- первичные ключи — UUID (номера не раскрывают объёмы бизнеса);
- деньги — `BIGINT` в копейках;
- статусы — строки с проверкой значений в приложении;
- записи о деньгах и журнал действий не удаляются.

## Таблицы

| Таблица | Назначение | Ключевые поля |
|---|---|---|
| `users` | сотрудники и покупатели | `login`, `role` (owner/admin/manager/accountant/client), `password_hash` (Argon2), `totp_secret`, `client_id` |
| `sessions` | серверные сессии | `token_hash` (SHA-256), `realm` (admin/client), `expires_at`, `revoked_at` |
| `login_attempts` | защита от перебора | `login`, `ip`, `success`, `created_at` |
| `activation_tokens` | одноразовые ссылки для установки пароля покупателем | `token_hash`, `expires_at`, `used_at` |
| `company_settings` | одна строка: режим продавца, реквизиты для оплаты, счётчик номеров договоров | `seller_regime`, `bank_*`, `next_contract_seq` |
| `cars` | реестр автомобилей | `vin`, `ownership_status` (owned/purchasing), `status`, `is_published`, `purchase_price_kopecks` (только сотрудникам), `sale_price_kopecks` |
| `car_photos` | фото (файлы в `storage/`) | `file_name`, `content_type`, `position` |
| `applications` | заявки с сайта и заказы | `kind`, `status`, `public_token`, `name`, `phone`, желаемые условия, `consent_*`, `source_ip_hash` |
| `application_events` | история статусов заявки | `from_status`, `to_status`, `public_message` |
| `clients` | покупатели | `party_type`, ФИО/наименование, паспорт или ИНН/ОГРН/КПП, `identity_verified*`, `timezone` |
| `contracts` | договоры | `number`, `status`, снимок условий (закупка, цена, наценка, взнос, срок), `is_consumer_deal`, `disclose_cost_to_buyer`, `no_interest_on_delay` |
| `schedule_items` | график платежей | `seq` (0 — взнос), `due_date`, `amount_kopecks` |
| `payments` | поступления | `amount_kopecks`, `received_on`, `method`, `document_ref`, `status` (confirmed/reversed), `reversal_reason`, `corrects_payment_id` |
| `payment_reports` | сообщения покупателя «Я оплатил» | `amount_kopecks`, `paid_on`, `status` (pending/matched/rejected) |
| `expenses` | расходы бизнеса | `spent_on`, `category`, `amount_kopecks`, `car_id` |
| `support_threads`, `support_messages` | обращения и переписка | `topic`, `contract_id`, `from_staff`, `body` |
| `notifications` | внутренние уведомления | `audience` (staff/client), `client_id`, `title`, `link`, `read_at` |
| `audit_log` | журнал действий | `actor_user_id`, `action`, `entity_type`, `entity_id`, `data`, `ip` |

## Таблицы версии 2

| Таблица | Назначение |
|---|---|
| `jobs`, `worker_heartbeats` | очередь фоновых задач и сигналы обработчика |
| `notification_rules` | расписание напоминаний: событие, дни, каналы |
| `consents` | согласия клиента по каналам (каждое изменение — новая запись) |
| `outbound_messages` | журнал сообщений клиентам: канал, текст, адрес в маске, статус и причина, ключ от повторов |
| `template_approvals` | утверждение шаблона юристом: версия, SHA-256 содержимого, ФИО юриста |
| `documents` | документы: шаблон, данные, проверки, текст и его SHA-256, статус, скан подписанного |
| `addenda`, `schedule_history` | доп. соглашения об изменении графика и прежние версии графика |
| `pledges`, `insurance_policies` | контроль залога и полисов |
| `staff_tasks` | задачи сотрудникам (ручные и от контроля сроков) |
| `backup_runs` | журнал резервных копий и проверок восстановления |

Также добавлены: `clients.phone_verified`, `clients.email_verified`, `company_settings.communication_policy`,
`contracts.schedule_version`. Суммы из SQL-агрегатов приводятся к BIGINT (`sum_kopecks`).

## Таблицы версии 3

| Таблица | Назначение |
|---|---|
| `knowledge_reviews` | заключения специалистов по записям библиотек (код, редакция, SHA-256, роль) |
| `tax_params` | параметры налоговых правил: значение, период, источник, черновик/утверждён/отозван |
| `tax_calendar_events` | налоговые сроки, внесённые бухгалтером |
| `cash_snapshots` | остатки денежных средств на дату |
| `car_checks` | результаты проверки автомобиля до покупки (история, источник, подтверждение) |
| `agent_runs` | запуски агентов: выводы, действия, ошибки |

Также добавлены: `company_settings.tax_regime`, `vat_payer`, `reserve_policy`; `cars.purchased_from`.

## Таблицы версии 4

| Таблица | Назначение |
|---|---|
| `bank_imports` | загруженные выписки: файл, SHA-256 (повтор не загрузится), счёт, период, счётчики |
| `bank_transactions` | входящие поступления: реквизиты платёжного документа, плательщик, назначение, предложенный договор с баллами и причинами, решение сотрудника, ссылка на платёж |
| `payment_intents` | онлайн-оплаты: сумма, провайдер, идентификатор у провайдера, статус, ключ идемпотентности, ссылка на платёж |

Также добавлены: `payments.source` (`staff` / `bank_statement` / `provider`), `payments.external_ref` (защита от двойного
учёта одной операции); `payments.confirmed_by` пуст только у онлайн-оплаты, проверенной у провайдера;
`company_settings.assistant_policy`. Миграция `0004`.

## Как считается остаток долга

Распределение платежей по графику **не хранится**, а вычисляется функцией `compute_ledger`
(`services/api/app/services/ledger.py`):

1. Берутся все платежи договора со статусом `confirmed`.
2. Их сумма распределяется по строкам графика по порядку `seq` (сначала взнос, затем самые ранние платежи).
3. Строка с остатком и сроком раньше сегодняшнего дня (по часовому поясу компании) — просрочена.
4. Остаток = сумма графика − подтверждённые платежи. Просрочка ничего не добавляет к долгу.

Поэтому сторнирование ошибочного платежа автоматически восстанавливает правильные остатки и статусы,
а админка и личный кабинет всегда показывают одно и то же.

## Неизменяемость

- Подписанный договор не редактируется через API (код 409). Изменения — дополнительным соглашением (версия 2).
- У проданного автомобиля нельзя менять VIN, цены и статусы.
- Платёж нельзя удалить — только сторнировать с причиной; исправленный платёж ссылается на исходный.
- `audit_log` пополняется в той же транзакции, что и изменение.
