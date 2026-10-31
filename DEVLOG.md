# DEVLOG
2026-10-30 — создан репозиторий, добавлены SPEC.md и AGENTS.md, папка docs/prompts
2026-10-30 17:20:00 (UTC+5) — Этап 1: Создан проектный каркас (Stage 1 project scaffold)
- Создана структура backend/app (main.py, config.py, db.py, models.py).
- Настроена конфигурация через pydantic-settings (.env.example).
- Реализованы SQLAlchemy 2 модели для таблиц events, registrations, notifications со всеми индексами из SPEC §4.
- Настроен Alembic и сгенерирована первая миграция (e0151147879b_initial_migration.py).
- Подготовлен docker-compose.yml (PostgreSQL 16, MailHog, backend) и backend/Dockerfile.
- Добавлены автотесты (backend/tests): проверка /health, применение миграций на чистой БД, уникальность (event_id, email) в registrations и (registration_id, kind, dedup_key) в notifications.
- Настроен CI GitHub Actions (.github/workflows/ci.yml) с сервисом Postgres 16.
- Обновлены README.md и DEVLOG.md.
2026-10-31 12:55:00 UTC — Этап 3: Отказ и повышение из очереди (Stage 3 Part A & B)
- Hardening тестов гонок (Part A):
  - Переведены конкурентные тесты в `backend/tests/test_stage2_registration.py` на `threading.Barrier` для синхронного запуска запросов.
  - Тест регистрации двух участников на последнее место запущен в цикле из 20 итераций.
  - Удалены неиспользуемые переменные `Session`/`sessionmaker` и устаревшие комментарии.
  - Проверена реакция тестов при снятии `.with_for_update()`: гонки выявляются стабильными падениями тестов.
  - В README добавлены разделы «Known limitations» и честный «Current state».
- Отказ и повышение из очереди (Part B, SPEC §5):
  - Добавлен эндпоинт `DELETE /api/tickets/{code}`, возвращающий `{"status": "cancelled"}`.
  - Реализован метод `cancel_registration` в `backend/app/services/registration.py` с соблюдением строгого порядка блокировок:
    1. Чтение `event_id` билета;
    2. Блокировка строки события `SELECT ... FROM events WHERE id=:id FOR UPDATE`;
    3. Повторное чтение статуса билета под блокировкой (`db.expire(registration)`);
    4. Для `confirmed`: перевод в `cancelled`, атомарный выбор первого участника листа ожидания по `(queued_at, id)`, перевод его в `confirmed` и создание outbox notification `waitlist_promoted` (`dedup_key='promoted'`) с `ON CONFLICT DO NOTHING`;
    5. Для `waitlist`: перевод в `cancelled` без продвижения очереди;
    6. Для `cancelled`: идемпотентный 200 no-op;
    7. Неизвестный код билета -> 404, начавшееся событие -> 409.
  - Написаны тесты с `threading.Barrier` и повторениями в `backend/tests/test_stage3_cancellation.py`.
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
