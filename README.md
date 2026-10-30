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

3. Health check endpoint:
   ```bash
   curl http://localhost:8000/health
   # Returns: {"status":"ok"}
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
