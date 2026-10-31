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
- Ревью (владелец + Claude): логика registration.py соответствует SPEC. Замечания: тесты гонок без синхронного старта потоков (слабая доказательная сила) и нет проверки, что они падают без блокировки; код билета возвращается при повторной регистрации чужого email (упрощение для демо, вынесено в README как ограничение). PR #2 смержен. Промпт этапа 2 (docs/prompts/02-registration.md) сохранён в репозитории позже запуска.

## 2026-10-31 17:55 (UTC+5) — Этап 3: отказ и повышение из очереди
Hardening тестов гонок (часть A):
- Конкурентные тесты в backend/tests/test_stage2_registration.py переведены на threading.Barrier для синхронного запуска запросов.
- Тест двух регистраций на последнее место запущен в цикле из 20 итераций.
- Удалены неиспользуемые Session/sessionmaker и устаревшие комментарии.
- Проверка «зубов»: при снятом .with_for_update() тесты гонок стабильно падают (assert 13 == 10; ['confirmed','confirmed']; UniqueViolation).
- В README добавлены разделы «Known limitations» и «Current state».

Отказ и повышение из очереди (часть B, SPEC §5):
- Эндпоинт DELETE /api/tickets/{code}, возвращает {"status": "cancelled"}.
- cancel_registration в backend/app/services/registration.py со строгим порядком блокировок: чтение event_id билета, блокировка события FOR UPDATE, повторное чтение статуса под блокировкой (db.expire(registration)).
- confirmed: перевод в cancelled, повышение первого из листа ожидания по (queued_at, id) в confirmed, outbox-запись waitlist_promoted (dedup_key='promoted') с ON CONFLICT DO NOTHING.
- waitlist: перевод в cancelled без продвижения очереди. cancelled: идемпотентный 200 no-op. Неизвестный код: 404, начавшееся событие: 409.
- Тесты с threading.Barrier и повторениями в backend/tests/test_stage3_cancellation.py.
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
