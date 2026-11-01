# DEVLOG

Время указано в UTC+5 (Астана). Роли: Claude — системный аналитик и ревьюер, Google Jules — инженер, владелец репозитория — постановка задач, ревью, merge.

## 2026-10-30 — Старт и решения
- Создан репозиторий, добавлены SPEC.md и AGENTS.md, папка docs/prompts.
- Выбрано Задание 9 (регистрация на мероприятия), срок сдачи 6 ноября.
- Стек: FastAPI, PostgreSQL, SQLAlchemy/Alembic, React, SSE, MailHog, docker compose. Консистентность держим в БД: блокировка строки события, уникальные индексы, outbox для писем.
- Промпт этапа 1 (docs/prompts/01-scaffold.md) отправлен в Jules. Файл с промптом закоммичен позже запуска.

## 2026-10-30 16:45 (UTC+5) — Этап 1: проектный каркас
- Создана структура backend/app (main.py, config.py, db.py, models.py).
- Настроена конфигурация через pydantic-settings (.env.example).
- Реализованы SQLAlchemy 2 модели events, registrations, notifications со всеми индексами из SPEC §4.
- Настроен Alembic, сгенерирована первая миграция (e0151147879b_initial_migration.py).
- Подготовлены docker-compose.yml (PostgreSQL 16, MailHog, backend) и backend/Dockerfile.
- Добавлены автотесты: /health, применение миграций на чистой БД, уникальность (event_id, email) и (registration_id, kind, dedup_key).
- Настроен CI GitHub Actions с сервисом Postgres 16.
- Обновлены README.md и DEVLOG.md.
- Ревью (владелец + Claude): PR #1 проверен, CI зелёный, main.py и models.py просмотрены вручную. Замечания к моделям вынесены в этап 2: CHECK на status, server_default для времени, CHECK на lower(email). PR #1 смержен.

## 2026-10-30 20:35 (UTC+5) — Этап 2: события и регистрация с блокировкой и листом ожидания
- Alembic-миграция (07fbb1c5f2d2): CHECK-ограничения (status IN ..., email = lower(email)) и server_default=now() для created_at и queued_at.
- Pydantic-схемы (schemas.py) для событий, регистрации и билетов.
- Логика регистрации (services/registration.py): SELECT ... FOR UPDATE на событии в единой транзакции; статус confirmed/waitlist по capacity; повторная регистрация возвращает существующий билет; реактивация отменённой регистрации в конец очереди; ticket_code через secrets.token_urlsafe(9); outbox-запись (kind='ticket', dedup_key='ticket') с ON CONFLICT DO NOTHING.
- Эндпоинты: POST /api/events, GET /api/events, GET /api/events/{id}, POST /api/events/{id}/registrations, GET /api/tickets/{code}.
- Тесты: 50 параллельных регистраций на 10 мест, 2 параллельные на последнее место, 10 параллельных на один email, нормализация email, порядок очереди и позиция в листе ожидания, CHECK-ограничения.
- Обновлены README.md и DEVLOG.md.
2026-10-31 17:25:00 UTC — Этап 4: Outbox worker и отправка писем через SMTP / MailHog (Stage 4)
- Реализован шаблонизатор писем `backend/app/workers/templates.py`:
  - Шаблоны на русском языке для 'ticket' и 'waitlist_promoted'.
  - Отображение времени начала события одновременно в UTC и Asia/Almaty (`ZoneInfo("Asia/Almaty")`).
  - Включение кода билета, статуса регистрации и инструкции по отказу через `DELETE /api/tickets/{code}`.
  - Разные темы писем (Subject) для каждого типа уведомления.
- Реализован фоновый воркер `backend/app/workers/outbox.py`:
  - Выборка до `OUTBOX_BATCH_SIZE` записей `notifications` с `status='pending'` по `FOR UPDATE SKIP LOCKED`.
  - Отправка email через стандартную библиотеку `smtplib` с фиксацией транзакции (`commit`) на каждое сообщение.
  - Успешная отправка: `status='sent'`, `sent_at=now()`.
  - Ошибки SMTP: `attempts += 1`, при достижении 5 неудачных попыток `status='failed'`.
  - Неизвестный `kind`: запись помечается `status='failed'`, воркер логирует предупреждение и продолжает работу.
  - Устойчивость к недоступности SMTP-сервера без падения процесса.
- Настройки и зависимости:
  - Добавлены параметры `SMTP_FROM`, `OUTBOX_POLL_SECONDS`, `OUTBOX_BATCH_SIZE` в `config.py` и `.env.example`.
  - В `requirements.txt` добавлен `aiosmtpd==1.4.6`.
- Добавлен сервис `worker` в `docker-compose.yml`, запускающий `python -m backend.app.workers.outbox` с зависимостями от postgres (healthy) и mailhog.
- Автотесты `backend/tests/test_stage4_outbox.py`:
  - Запуск реального in-process SMTP-сервера (`aiosmtpd.controller.Controller`) в тестовой фикстуре.
  - Проверка доставки билета один раз и корректности заполнения полей `status='sent'` и `sent_at`.
  - Параллельная обработка двумя воркерами (с `threading.Barrier`) без дублирования отправки.
  - Проверка повторных попыток при недоступности SMTP и переход в `status='failed'` после 5 ошибок, а также успешная доставка после восстановления сервера.
  - Сквозной тест (end-to-end): регистрация двух участников на 1 место, отмена первого билета, запуск воркера и фиксация ровно 3 писем (2 ticket + 1 waitlist_promoted).
  - Проверка холостого запуска при пустом outbox.
  - Обработка неизвестного `kind` с переводом в `status='failed'` без падения воркера.
- Обновлены README.md и DEVLOG.md.
2026-10-30 20:35:00 (UTC+5) — Этап 2: События и регистрация с блокировкой и листом ожидания (Stage 2)
- Добавлена Alembic-миграция (07fbb1c5f2d2) с CHECK-ограничениями (status IN ..., email = lower(email)) и server_default=now() для created_at и queued_at.
- Реализованы Pydantic-схемы (schemas.py) для создания/получения событий, регистрации и просмотра билетов.
- Написана бизнес-логика регистрации (services/registration.py) с подзапросом блокировки строки SELECT ... FOR UPDATE на событии в единой транзакции:
  - Автоматическое определение статуса confirmed / waitlist по capacity события.
  - Обработка повторной регистрации (возврат существующего билета для активного пользователя).
  - Реактивация отменённой регистрации (перевод в конец очереди с новыми queued_at = now()).
  - Генерация ticket_code с secrets.token_urlsafe(9).
  - Вставка записи outbox notification (kind='ticket', dedup_key='ticket') с ON CONFLICT DO NOTHING.
- Реализованы API-эндпоинты POST /api/events, GET /api/events, GET /api/events/{id}, POST /api/events/{id}/registrations, GET /api/tickets/{code}.
- Добавлены интеграционные и конкурентные тесты (backend/tests):
  - 50 параллельных регистраций на 10 мест (ровно 10 confirmed, 40 waitlist).
  - 2 параллельные регистрации на последнее место.
  - 10 параллельных повторных регистраций на 1 email.
  - Нормализация email (trim + lower).
  - Порядок очереди и позиция в листе ожидания.
  - Проверка срабатывания CHECK-ограничений в БД.
- Обновлены README.md и DEVLOG.md.
- Промпт этапа 3 (docs/prompts/03-cancel-waitlist.md) сохранён до запуска в Jules.

## 2026-10-31 21:58 (UTC+5) — Ручная проверка этапов 1–3
- `docker compose up -d --build` проверен на Windows (Docker Desktop): миграции применились, `/health` отвечает `{"status":"ok"}`.
- Сценарий через Swagger: событие на 1 место, регистрация a@test.com (confirmed), b@test.com (waitlist), отмена билета a, билет b стал confirmed, счётчики сошлись.

## 2026-10-31 22:25 (UTC+5) — Этап 4: outbox-воркер и отправка писем через SMTP / MailHog
- Шаблоны писем (backend/app/workers/templates.py): русский текст для 'ticket' и 'waitlist_promoted', время события в UTC и Asia/Almaty, код билета, статус, инструкция по отказу через DELETE /api/tickets/{code}, разные темы писем.
- Воркер (backend/app/workers/outbox.py): выборка pending-записей по FOR UPDATE SKIP LOCKED, отправка через smtplib с коммитом на каждое письмо; успех: status='sent', sent_at=now(); ошибка SMTP: attempts+1, после 5 попыток status='failed'; неизвестный kind: failed, воркер продолжает работу; недоступный SMTP воркер не роняет.
- Настройки: SMTP_FROM, OUTBOX_POLL_SECONDS, OUTBOX_BATCH_SIZE (config.py, .env.example); в requirements.txt добавлен aiosmtpd==1.4.6.
- В docker-compose.yml добавлен сервис worker (зависит от postgres healthy и mailhog).
- Тесты (backend/tests/test_stage4_outbox.py) на реальном in-process SMTP-сервере: доставка одного письма, два параллельных воркера без дублей, ретраи и переход в failed, доставка после восстановления SMTP, сквозной сценарий (3 письма: 2 ticket + 1 waitlist_promoted), пустой outbox, неизвестный kind.
- Обновлены README.md и DEVLOG.md. Этап 4 пришёл в том же PR #3, что и этап 3.

- ## 2026-11-01 17:50 (UTC+5) — Ручная проверка этапа 4
- `git pull` и `docker compose up -d --build`: поднялись четыре контейнера (postgres, mailhog, backend, worker), `/health` отвечает.
- Сценарий через Swagger: событие на 1 место, регистрация a@test.com и b@test.com, отмена билета a. В MailHog пришли три письма (ticket для a, ticket для b, waitlist_promoted для b), каждое один раз.
- Накопившиеся в outbox письма вчерашнего теста (3 шт.) доставлены при первом запуске воркера: очередь пережила перезапуск.


## 2026-11-01 18:15 (UTC+5) — Этап 5: планировщик напоминаний и перенос события
- Миграция f900bca402e9: в CHECK статусов notifications добавлен 'skipped'.
- Планировщик backend/app/workers/scheduler.py: цикл с опросом, функция run_tick(session, now) для подмены времени в тестах. Напоминание reminder_24h создаётся для confirmed-участников событий, до начала которых осталось не более 24 часов; ключ дедупликации — дата начала события (ISO), INSERT ... ON CONFLICT DO NOTHING. Безопасно при нескольких экземплярах планировщика.
- PATCH /api/organizer/{secret}: перенос события. Секрет сверяется через secrets.compare_digest, неверный секрет даёт 404, дата должна быть с часовым поясом и в будущем (иначе 422). В одной транзакции под FOR UPDATE: смена даты, старые pending-напоминания помечаются 'skipped', всем confirmed и waitlist создаётся event_rescheduled.
- Outbox-воркер перед отправкой reminder_24h и event_rescheduled перепроверяет регистрацию: если отменена, уведомление 'skipped', письмо не уходит.
- Русские шаблоны писем с временем в UTC и Asia/Almaty. В docker-compose добавлен сервис scheduler.
- Тесты: 35 passed (9 новых).
- Ограничение среды Jules: docker compose в его песочнице не запустился, проверка сервиса scheduler выполнена вручную (см. следующую запись).
- Ревью (владелец + Claude): PR #5 проверен по описанию и результатам тестов; замечание про узкое окно гонки между тиком и переносом вынесено в Known limitations.
