# Event Registration Service

Service for event registration with capacity limits, waitlist, unique ticket codes, check-in, live counters, and email notifications via outbox.

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
- **Not implemented yet:**
  - SSE live counters and stream endpoints (Stage 6b).
  - Frontend UI (Stage 7).
