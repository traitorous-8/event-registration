# Event Registration Service

Service for event registration with capacity limits, waitlist, unique ticket codes, check-in, live counters, and email notifications via outbox.

## For Reviewers (Mad Devs, Task 9)

### What we built it with and why
- **Claude** (claude.ai chat) acted as systems analyst and reviewer: wrote the specification (SPEC.md), made architecture decisions, wrote the prompts for Jules, reviewed every PR and helped with debugging. Chosen for careful requirements work and code analysis.
- **Google Jules** acted as the engineer: implements a task from a ready prompt asynchronously and opens a PR on GitHub. Chosen because every task arrives as a PR with commit history, which gives a verifiable course of work.
- The repository owner sets the tasks, checks every PR (changed files, test count, CI), merges, and verifies the result by hand on a running stack.

### Prompts, decision log and timeline
- Prompts for Jules: `docs/prompts/` (one file per task, including the failed attempts of stages 6 and 7).
- Decision log and timeline with timestamps: `DEVLOG.md`, including incidents (stage 6a deleted the stage 5 code and was rolled back with `git revert`; a Jules error with `node_modules` in stage 7).
- Agent session exports (jsonl) are not attached; prompts and DEVLOG are provided instead. Commit and PR history (#1-#9) shows that the work was incremental.
- Some prompt files were committed after the tasks were started; this is noted in the commit messages and in DEVLOG.

### How to run
Requires Docker and Docker Compose.

    git clone https://github.com/traitorous-8/event-registration.git
    cd event-registration
    docker compose up -d --build

- Frontend: http://localhost:3000
- API and Swagger: http://localhost:8000/docs
- Emails (MailHog): http://localhost:8025
- Containers: postgres, mailhog, backend, worker (email delivery), scheduler (reminders), frontend.
- Tests: backend `cd backend && pytest -v` (58 tests, needs a test database, see the section above); frontend `cd frontend && npm test`.

### Project status
**Works** (verified by automated tests and by hand on Docker Desktop, Windows):
- events with a seat limit, registration by email without duplicates, waitlist, ticket with a code, cancellation with automatic promotion of the first person in the queue;
- race protection: event row lock, unique indexes, atomic check-in (verified by parallel tests);
- emails through an outbox (ticket, seat from the waitlist, 24-hour reminder, event reschedule), exactly one per event;
- check-in by ticket code, organizer screen (counters, participants list, reschedule);
- live updates over SSE: counters, participants list and ticket status change in several open tabs without a page reload;
- React client (separate container, nginx proxies /api to the backend, SSE without buffering).

**Not done / limitations:** see "Known limitations" above. Additionally: there is no login or roles (the organizer is identified by a secret link shown only once); the frontend has minimal styling and no browser e2e tests; Jules could not run docker compose in its sandbox, so the stack was verified manually by the owner.

### What we would do next
1. Email confirmation, with the ticket code delivered only by email (currently it is returned in the registration response).
2. Postgres `LISTEN/NOTIFY` instead of the in-process bus, so several backend workers can run.
3. Organizer login (account or one-time link with revocation) instead of a permanent secret in the URL.
4. Reminder subject based on the real time left, and closing the narrow race window between the scheduler and event rescheduling.
5. Browser e2e tests (Playwright), UI polish and accessibility.
6. Rate limiting for registration requests and monitoring of the email queue.

### Third-party solutions and templates
No ready-made project templates or generators were used. Open-source libraries: FastAPI, SQLAlchemy, Alembic, PostgreSQL, React, Vite, react-router-dom, aiosmtpd, MailHog. [If Jules created the frontend scaffold with `npm create vite`, add that here.]

## Tech Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic
- **Database:** PostgreSQL 16
- **Email:** SMTP -> MailHog
- **Orchestration:** Docker Compose

## Requirements

- Docker & Docker Compose (or Python 3.12+ and PostgreSQL 16 installed locally)

## Getting Started (Docker Compose)

1. Copy `.env.example` to `.env` (optional, defaults are configured for docker-compose):
   ```bash
   cp .env.example .env
   ```

2. Start the full stack with Docker Compose:
   ```bash
   docker compose up --build
   ```
   This starts:
   - PostgreSQL 16 on port `5432`
   - MailHog on port `1025` (SMTP) and `8025` (Web UI at `http://localhost:8025`)
   - FastAPI Backend on `http://localhost:8000` (runs migrations automatically on startup)
   - Outbox Email Worker (running `python -m backend.app.workers.outbox` to deliver emails via MailHog)

3. Endpoints:
   - `GET /health` -> `{"status": "ok"}`
   - `POST /api/events` -> Create an event (`{title, description, starts_at, capacity}`) -> returns event data with `organizer_secret`
   - `GET /api/events` -> List all public events (with `confirmed_count` and `waitlist_count`)
   - `GET /api/events/{id}` -> Public details for a specific event
   - `POST /api/events/{id}/registrations` -> Register for an event (`{email}`) -> returns `{status, ticket_code}`
   - `GET /api/tickets/{code}` -> Get ticket status, position in waitlist (if waitlisted), and event details
   - `DELETE /api/tickets/{code}` -> Cancel registration (idempotent, promotes earliest waitlist participant if confirmed; returns 409 if already checked in)
   - `POST /api/organizer/{secret}/checkin` -> Check in participant by ticket code (`{ticket_code}`) -> 200 on success, 404 (unknown or wrong event), 409 (already checked in), 422 (not confirmed)
   - `GET /api/organizer/{secret}` -> Organizer view with event details, live counters (`confirmed`, `waitlist`, `checked_in`), and participant list ordered by `(queued_at, id)`
   - `PATCH /api/organizer/{secret}` -> Reschedule event (`{starts_at}`)

## Frontend

The frontend is a single-page application built with React 18, Vite, and React Router 6, communicating with the backend over relative `/api` paths with plain CSS styling.

### Pages
- `/` — Список мероприятий: просмотр всех событий с текущими счётчиками мест и форма создания нового мероприятия. После создания выводится ссылка организатора (`/organizer/:secret`) с кнопкой копирования и предупреждением о безопасности.
- `/events/:id` — Страница мероприятия: детали, время старта в локальном часовом поясе, live-счётчики мест через SSE (`/api/events/:id/stream`), форма регистрации по email, отображение выданного билета и сохранение билетов в `localStorage`.
- `/ticket/:code` — Страница билета: статус билета и позиция в очереди в реальном времени (`/api/tickets/:code/stream`), кнопка добровольного отказа от участия с диалогом подтверждения и обработкой блокировки отмены после чекина (409).
- `/organizer/:secret` — Панель организатора: live-счётчики (`confirmed`, `waitlist`, `checked_in`) и таблица участников через SSE (`/api/organizer/:secret/stream`), форма быстрой отметки входа (чек-ин по коду билета), форма переноса даты события (`PATCH`), и экран запрета доступа при неверном секрете (404).

### Running with Docker Compose
Frontend запускается в docker-compose на порту `3000`:
```bash
docker compose up --build
```
Интерфейс доступен по адресу `http://localhost:3000`. Запросы к `/api/` проксируются через Nginx на `http://backend:8000` с отключённым буферизированием (`proxy_buffering off; proxy_cache off;`) и увеличенным таймаутом чтения (`proxy_read_timeout 3600s;`), что обеспечивает стабильную работу Server-Sent Events (SSE) без разрывов потока.

### Running Frontend Locally (npm)
1. Установите зависимости и запустите dev-сервер:
   ```bash
   cd frontend
   npm ci
   npm run dev
   ```
   Dev-сервер Vite стартует на `http://localhost:3000` и настроен на проксирование `/api` на `http://localhost:8000`.

2. Запуск тестов фронтенда:
   ```bash
   cd frontend
   npm test
   ```

3. Сборка продакшен-бандла:
   ```bash
   cd frontend
   npm run build
   ```

## Local Development & Running Tests

1. Create a Python virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Ensure PostgreSQL is running and test database exists (`event_registration_test`):
   ```bash
   createdb event_registration_test
   ```

3. Run tests using `pytest`:
   ```bash
   cd backend
   pytest -v
   ```

4. Run the Outbox Worker locally:
   ```bash
   python -m backend.app.workers.outbox
   ```
   Sent emails can be viewed in the MailHog web interface at `http://localhost:8025`.

## Environment Variables

- `DATABASE_URL`: PostgreSQL connection URL (e.g. `postgresql://postgres:postgres@localhost:5432/event_registration`).
- `SMTP_HOST`: Host of the SMTP server (default: `localhost`, in docker-compose: `mailhog`).
- `SMTP_PORT`: Port of the SMTP server (default: `1025`).
- `SMTP_FROM`: Sender email address (default: `noreply@events.local`).
- `OUTBOX_POLL_SECONDS`: Polling interval in seconds for the outbox worker (default: `2.0`).
- `OUTBOX_BATCH_SIZE`: Batch size for picking pending notifications (default: `20`).
- `SCHEDULER_POLL_SECONDS`: Polling interval in seconds for the reminder scheduler worker (default: `30.0`).
- `SSE_HEARTBEAT_SECONDS`: Interval in seconds between SSE heartbeat ping comments (default: `15.0`).

## Server-Sent Events (SSE) Live Updates

The backend provides three Server-Sent Events (SSE) endpoints (media type `text/event-stream`):

1. **Public Event Stream (`GET /api/events/{id}/stream`):**
   - Streams event count snapshots: event `counts` with `{confirmed, waitlist}`.
   - Example with curl:
     ```bash
     curl -N http://localhost:8000/api/events/1/stream
     ```
   - Stream output:
     ```
     event: counts
     data: {"confirmed": 5, "waitlist": 2}
     ```
   - Public streams never contain emails, ticket codes, or organizer secrets.

2. **Organizer Stream (`GET /api/organizer/{secret}/stream`):**
   - Validates organizer secret in constant time (`secrets.compare_digest`); returns 404 before streaming if secret is invalid.
   - Streams event `counts` with `{confirmed, waitlist, checked_in}` and event `participants` with the list of participants (email, status, ticket_code, queued_at, checked_in_at).
   - Example with curl:
     ```bash
     curl -N http://localhost:8000/api/organizer/<secret>/stream
     ```

3. **Ticket Stream (`GET /api/tickets/{code}/stream`):**
   - Returns 404 before streaming if ticket code is not found.
   - Streams event `ticket` with `{status, position_in_waitlist}` for that single ticket.
   - Example with curl:
     ```bash
     curl -N http://localhost:8000/api/tickets/<ticket_code>/stream
     ```

- **Snapshots and Heartbeats:**
  - Upon connection, each stream immediately delivers a full snapshot.
  - Whenever an event changes (registration, reactivation, cancellation/promotion, check-in, reschedule), a new snapshot is pushed to all subscribed streams.
  - When idle, a heartbeat comment line (`: ping\n\n`) is emitted every `SSE_HEARTBEAT_SECONDS` (default: 15 seconds).
  - Snapshot database reads run in threadpools with short-lived sessions to keep the async event loop non-blocking.
  - Client disconnection cleans up subscriptions immediately.

- **Single-Worker In-Process Bus Limitation:**
  - The live-update pub/sub bus (`backend/app/events_bus.py`) is currently in-process using bounded asyncio queues (`maxsize=100`, oldest message dropped if full).
  - Because pub/sub messages are dispatched in-process, uvicorn must run with a single worker (`workers=1`), as configured in `docker-compose.yml`. For multi-process horizontal scaling, an external broker or PostgreSQL `LISTEN`/`NOTIFY` would be used.

## Scheduler & Rescheduling

- **Reminder Scheduler (`backend/app/workers/scheduler.py`):**
  - Runs in a loop polling every `SCHEDULER_POLL_SECONDS` (default: 30s).
  - Finds all events where `now < starts_at <= now + 24h` and creates `reminder_24h` notifications with `dedup_key = starts_at (ISO)` for all `confirmed` registrations using `INSERT ... ON CONFLICT DO NOTHING`.
  - Waitlist and cancelled registrations receive no reminder; if a waitlisted participant is promoted inside the 24h window, their reminder is created on the next tick.
  - Events that already started are ignored. If the scheduler restarts after downtime, it catches up on pending reminders for future events without generating reminders for past events.
  - Safe for multiple parallel scheduler instances without extra locking, relying on the database unique constraint on `(registration_id, kind, dedup_key)`.
  - The tick logic is encapsulated in `run_tick(session, now)` allowing deterministic time injection in tests.

- **Reschedule Endpoint (`PATCH /api/organizer/{secret}`):**
  - Accepts `{starts_at: "<ISO datetime>"}`.
  - Verifies organizer secret using constant-time comparison `secrets.compare_digest`; invalid secret returns `404 Not Found` (never exposing event existence).
  - Validates `starts_at` is timezone-aware and in the future (returns `422` otherwise).
  - If `starts_at` is identical to current event time, returns `200` as a no-op without creating notifications.
  - In a single transaction under `SELECT ... FOR UPDATE` event lock:
    1. Updates `starts_at`.
    2. Marks pending `reminder_24h` notifications of this event whose `dedup_key` differs from the new date as `'skipped'`.
    3. Inserts `event_rescheduled` notifications (dedup_key = new starts_at ISO) for all `confirmed` and `waitlist` registrations (`ON CONFLICT DO NOTHING`).
  - Response returns the updated public event data, never exposing `organizer_secret`.

- **Outbox Worker Re-check:**
  - Before sending `reminder_24h` or `event_rescheduled` emails, the outbox worker re-checks the recipient's registration status. If it is `cancelled`, the notification is marked `'skipped'` and no email is sent.
  - Plain-text Russian email templates format times in both UTC and `Asia/Almaty` timezones with distinct subjects for reminders and rescheduling.

## Known limitations

- **Ticket code in registration response:** The ticket code is returned directly in the registration API response, and there is no email confirmation sent on registration (this is a demo simplification; in a real product it would only be sent by email).
- **In-process live-update bus:** The live-update notification bus is currently in-process, which limits backend deployment to a single uvicorn worker process.
- **Outbox delivery window:** The transactional outbox has a small window between sending an email and marking it sent in the database (at-least-once delivery, deduplicated by the unique key constraint on `(registration_id, kind, dedup_key)`).
- * Reminder subject says "in 24 hours": the reminder email subject always reads "in 24 hours", even when the event is less than a day away (for example, when someone registers or is promoted from the waitlist inside the 24-hour window).
  * Scheduler/reschedule race: the scheduler tick does not lock the event row. If an organizer reschedules the event in the same instant a tick reads the old start time, a reminder for the old date may be queued after the old reminders were marked skipped. The window is very small.

## Current state

- **Implemented:**
  - Database schema, Alembic migrations, constraints, and indexes for `events`, `registrations`, and `notifications` (including `'skipped'` status).
  - Event creation and listing (`POST /api/events`, `GET /api/events`, `GET /api/events/{id}`).
  - Registration with capacity limits, waitlist positioning, and idempotent re-registration (`POST /api/events/{id}/registrations`).
  - Ticket details retrieval (`GET /api/tickets/{code}`).
  - Ticket cancellation (`DELETE /api/tickets/{code}`) with atomic waitlist promotion and outbox notification, blocking cancellation for checked-in participants with 409 Conflict.
  - Participant check-in endpoint (`POST /api/organizer/{secret}/checkin`) executing atomic single-statement SQL UPDATE RETURNING, with granular 404/409/422 diagnostics.
  - Organizer event view (`GET /api/organizer/{secret}`) with event details, counters (`confirmed`, `waitlist`, `checked_in`), and ordered participant list (`(queued_at, id)`).
  - Outbox email sending worker (`backend/app/workers/outbox.py`) delivering plain-text Russian emails via SMTP (MailHog) with retry handling and `FOR UPDATE SKIP LOCKED`.
  - Scheduler worker (`backend/app/workers/scheduler.py`) for automated 24h reminders and catch-up on restart.
  - Event rescheduling endpoint (`PATCH /api/organizer/{secret}`) with atomic cancellation/skipping of outdated reminders and rescheduling notices.
  - Email templates (`backend/app/workers/templates.py`) formatting dates in UTC and Asia/Almaty timezones for tickets, promotions, 24h reminders, and rescheduling notices.
  - Pessimistic locking (`SELECT ... FOR UPDATE` with event-first lock order) ensuring safe concurrency under race conditions.
  - Comprehensive race condition, barrier-synchronized concurrency tests, and check-in tests.
  - Server-Sent Events (SSE) live-update endpoints (`GET /api/events/{id}/stream`, `GET /api/organizer/{secret}/stream`, `GET /api/tickets/{code}/stream`) backed by an in-process event bus, heartbeat pings, and non-blocking database snapshot reads (Stage 6b).
  - React 18 single-page frontend application (`frontend/`) with live SSE counters, event creation, registration, ticket view/cancellation, and organizer dashboard with check-in and rescheduling (Stage 7).
- **Not implemented yet:**
  - None (all MVP backend, outbox, scheduler, SSE, and frontend stages completed).
