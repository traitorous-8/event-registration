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
   - `POST /api/organizer/{secret}/checkin` -> Check in participant by ticket code (`{ticket_code}`) -> returns `{email, ticket_code, checked_in_at}`
   - `GET /api/organizer/{secret}` -> Organizer event view with live counters (`confirmed_count`, `waitlist_count`, `checked_in_count`) and participants list ordered by `(queued_at, id)`

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

## Known limitations

- **Ticket code in registration response:** The ticket code is returned directly in the registration API response, and there is no email confirmation sent on registration (this is a demo simplification; in a real product it would only be sent by email).
- **In-process live-update bus:** The live-update notification bus is currently in-process, which limits backend deployment to a single uvicorn worker process.
- **Outbox delivery window:** The transactional outbox has a small window between sending an email and marking it sent in the database (at-least-once delivery, deduplicated by the unique key constraint on `(registration_id, kind, dedup_key)`).

## Current state

- **Implemented:**
  - Database schema, Alembic migrations, constraints, and indexes for `events`, `registrations`, and `notifications`.
  - Event creation and listing (`POST /api/events`, `GET /api/events`, `GET /api/events/{id}`).
  - Registration with capacity limits, waitlist positioning, and idempotent re-registration (`POST /api/events/{id}/registrations`).
  - Ticket details retrieval (`GET /api/tickets/{code}`).
  - Ticket cancellation (`DELETE /api/tickets/{code}`) with atomic waitlist promotion and outbox notification (cancellation rejected with 409 if already checked in).
  - Participant check-in (`POST /api/organizer/{secret}/checkin`) using an atomic SQL UPDATE statement with detailed failure handling (404, 409, 422).
  - Organizer event view (`GET /api/organizer/{secret}`) with counters (`confirmed_count`, `waitlist_count`, `checked_in_count`) and participants list.
  - Outbox email sending worker (`backend/app/workers/outbox.py`) delivering plain-text Russian emails via SMTP (MailHog) with retry handling and `FOR UPDATE SKIP LOCKED`.
  - Email templates (`backend/app/workers/templates.py`) formatting dates in UTC and Asia/Almaty timezones.
  - Pessimistic locking (`SELECT ... FOR UPDATE` with event-first lock order) ensuring safe concurrency under race conditions.
  - Comprehensive race condition and outbox delivery tests with barrier-synchronized concurrency.
- **Not implemented yet:**
  - Live updates over SSE (Stage 6b).
  - Frontend UI (Stage 7).
