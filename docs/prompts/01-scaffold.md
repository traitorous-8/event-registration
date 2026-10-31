Read SPEC.md and AGENTS.md first and follow them.

Task: Stage 1 from SPEC §10, project scaffold only. No business logic.

Deliver:

backend/: FastAPI app (app/main.py) with GET /health returning {"status": "ok"}; config via environment variables (DATABASE_URL, SMTP_HOST, SMTP_PORT); db.py with SQLAlchemy 2 engine/session.
models.py with the three tables from SPEC §4 (events, registrations, notifications), including all unique and composite indexes exactly as specified. Alembic set up, one initial migration that creates them.
docker-compose.yml: postgres:16, mailhog, backend (migrations run on start). Frontend is not part of this stage.
backend/tests/: pytest setup using a separate test database. Tests: (a) /health returns 200; (b) migrations apply on a clean DB; (c) the unique index on registrations (event_id, email) and the unique index on notifications (registration_id, kind, dedup_key) actually reject duplicates.
.github/workflows/ci.yml: run pytest on push and pull request with a Postgres service.
.env.example, requirements.txt with pinned versions, README.md with run and test instructions.
Append a timestamped entry to DEVLOG.md describing what was done and the decisions made.

Rules: one PR for this stage, small commits in the format from AGENTS.md. In the PR description state what is done, what is verified by tests (include pytest output), and what is not done. Do not implement endpoints beyond /health.
