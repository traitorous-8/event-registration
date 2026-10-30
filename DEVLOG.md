# DEVLOG
2026-10-30 — создан репозиторий, добавлены SPEC.md и AGENTS.md, папка docs/prompts
2026-10-30 11:45:00 UTC — Этап 1: Создан проектный каркас (Stage 1 project scaffold)
- Создана структура backend/app (main.py, config.py, db.py, models.py).
- Настроена конфигурация через pydantic-settings (.env.example).
- Реализованы SQLAlchemy 2 модели для таблиц events, registrations, notifications со всеми индексами из SPEC §4.
- Настроен Alembic и сгенерирована первая миграция (e0151147879b_initial_migration.py).
- Подготовлен docker-compose.yml (PostgreSQL 16, MailHog, backend) и backend/Dockerfile.
- Добавлены автотесты (backend/tests): проверка /health, применение миграций на чистой БД, уникальность (event_id, email) в registrations и (registration_id, kind, dedup_key) в notifications.
- Настроен CI GitHub Actions (.github/workflows/ci.yml) с сервисом Postgres 16.
- Обновлены README.md и DEVLOG.md.
