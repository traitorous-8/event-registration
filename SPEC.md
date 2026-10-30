# SPEC: Сервис регистрации на мероприятия

Тестовое задание Mad Devs, Задание 9. Источник требований: документ «Задания Agentic Developer».

## 1. Цель и границы

Организатор создаёт событие с лимитом мест. Участники регистрируются по email, получают билет с кодом. Когда места кончились, они попадают в лист ожидания. На входе билет отмечается один раз.

**Вне объёма:** оплата, изменение лимита мест, роли и пароли, реальная отправка почты (используется MailHog), сканер QR (вместо него ввод кода).

## 2. Стек и причины

| Часть | Выбор | Причина |
|---|---|---|
| Backend | Python 3.12, FastAPI | быстро писать, async, автогенерация OpenAPI |
| БД | PostgreSQL 16 | нужны блокировки строк и частичные уникальные индексы |
| ORM / миграции | SQLAlchemy 2, Alembic | |
| Frontend | React + Vite | |
| Live | SSE | обновления идут только сервер → клиент, проще WebSocket |
| Почта | SMTP → MailHog | письма видно в UI, настоящий SMTP не нужен |
| Запуск | docker compose | |

## 3. Доступ (без логина)

- Создатель события получает **секретную ссылку организатора** `/organizer/{organizer_secret}`. Секрет хранится в событии.
- Участник управляет регистрацией по **коду билета** `/ticket/{ticket_code}`.
- Публичная страница события `/events/{id}`.

## 4. Модель данных

**events:** id, title, description, starts_at (timestamptz, UTC), capacity (>0), organizer_secret, created_at.

**registrations:** id, event_id, email (нормализован: trim + lower), ticket_code (уникальный, `secrets.token_urlsafe(9)`), status (`confirmed` | `waitlist` | `cancelled`), queued_at, checked_in_at (nullable), created_at.
- Уникальный индекс `(event_id, email)`.
- Индекс `(event_id, status, queued_at, id)`.

**notifications (outbox):** id, registration_id, kind, dedup_key, payload (jsonb), status (`pending` | `sent` | `failed`), attempts, created_at, sent_at.
- Уникальный индекс `(registration_id, kind, dedup_key)`.

## 5. Правила и как они обеспечиваются

| Требование | Решение |
|---|---|
| Повторная регистрация на тот же email не создаёт второго места | Уникальный `(event_id, email)`. Если запись `cancelled`, она реактивируется и становится в **конец** очереди (`queued_at = now()`). Если активна, возвращается 200 с текущим статусом. |
| Два человека на последнее место | Транзакция, в начале `SELECT ... FROM events WHERE id=:id FOR UPDATE`. Дальше считаем `confirmed`, и если `< capacity` ставим `confirmed`, иначе `waitlist`. |
| Отказ → первый из листа получает место и письмо | В той же транзакции, под той же блокировкой: берём первую `waitlist` по `(queued_at, id)`, ставим `confirmed`, создаём notification `waitlist_promoted`. |
| Чекин один раз | Атомарный `UPDATE registrations SET checked_in_at=now() WHERE ticket_code=:c AND status='confirmed' AND checked_in_at IS NULL RETURNING *`. Нет строки: различаем 404 (нет кода), 409 (уже отмечен), 422 (не `confirmed`). |
| Ровно одно письмо | Письма идут только через outbox. Уникальный `(registration_id, kind, dedup_key)` + `INSERT ... ON CONFLICT DO NOTHING`. |
| Напоминание за сутки, ровно одно | Планировщик раз в 30 с: `confirmed` участники событий, где `starts_at - now() <= 24h` и `starts_at > now()`, создают notification `reminder_24h` с `dedup_key = starts_at (ISO)`. После переноса события при новой дате напоминание уйдёт один раз для новой даты. |
| Перенос события | `PATCH` организатора меняет `starts_at`, создаёт `event_rescheduled` (dedup_key = новая дата) для всех `confirmed` и `waitlist`. |
| Перезапуск сервера | Всё состояние и очередь писем в БД. Планировщик при старте догоняет пропущенное: событие ещё не началось, напоминание нужно, значит создаётся и уходит. Для событий, которые уже начались, напоминание не создаётся. |
| Отправка письма | Воркер берёт `pending` через `FOR UPDATE SKIP LOCKED`, шлёт SMTP, ставит `sent`. Ошибка: `attempts+1`, после 5 попыток `failed`. Окно «письмо ушло, статус не записан» принимается и описывается в README. |

## 6. API

Все ответы JSON, время в UTC (ISO 8601).

- `POST /api/events` → событие + `organizer_secret`
- `GET /api/events`, `GET /api/events/{id}` → публичные данные + `confirmed_count`, `waitlist_count`
- `POST /api/events/{id}/registrations` `{email}` → `{status, ticket_code}`
- `GET /api/tickets/{code}` → статус, место в очереди, данные события
- `DELETE /api/tickets/{code}` → отказ (идемпотентен)
- `GET /api/organizer/{secret}` → событие, счётчики, список участников
- `PATCH /api/organizer/{secret}` `{starts_at}` → перенос
- `POST /api/organizer/{secret}/checkin` `{ticket_code}` → 200 / 404 / 409 / 422
- `GET /api/events/{id}/stream` и `GET /api/organizer/{secret}/stream` → SSE
- `GET /health`

## 7. Live-обновления

SSE, события `counts` (`confirmed`, `waitlist`, `checked_in`) и `registration` (смена статуса). Публикация после **commit** транзакции. Шина сообщений в памяти процесса, поэтому один worker uvicorn (ограничение записано в README, следующий шаг: Postgres LISTEN/NOTIFY). Клиент при переподключении перечитывает состояние через GET.

## 8. Frontend

1. Список событий + форма создания (после создания показываем ссылку организатора).
2. Страница события: описание, счётчики, форма регистрации, результат (билет или лист ожидания).
3. Страница билета: код, статус, позиция в очереди (live), кнопка отказа.
4. Страница организатора: счётчики live, список участников, поле чекина по коду, перенос даты.

## 9. Приёмка (все пункты покрыты автотестами)

1. 50 параллельных регистраций на событие с лимитом 10: ровно 10 `confirmed`, 40 `waitlist`.
2. Две параллельные регистрации на последнее место: одна `confirmed`, одна `waitlist`.
3. Повтор email: одна запись, одно письмо с билетом.
4. Отказ `confirmed`: первый из листа становится `confirmed`, письмо одно, порядок очереди сохранён.
5. Параллельный чекин одного кода: ровно один 200.
6. Напоминание создаётся один раз при многократных тиках планировщика.
7. Перенос события: письма всем `confirmed` и `waitlist`, повторный перенос на ту же дату писем не создаёт.
8. Перезапуск: пропущенное напоминание создаётся при старте.
9. SSE: два подключённых клиента получают обновление счётчика.

## 10. Этапы

1. Каркас: compose, FastAPI, Alembic, схема, CI с тестами.
2. События и регистрация с блокировкой и листом ожидания + тесты гонок.
3. Отказ и повышение из очереди, билет.
4. Outbox, воркер, MailHog, письма регистрации и повышения.
5. Планировщик: напоминания, перенос.
6. Чекин, организатор, SSE.
7. Frontend.
8. README, честное описание состояния, `DEVLOG.md`, эссе.
