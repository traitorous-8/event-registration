Read SPEC.md and AGENTS.md first and follow them. Stage 1 is merged into main; start from the current main.

Task: Stage 2 from SPEC §10, events and registration with locking and waitlist. Cancellation, check-in, email sending, scheduler and SSE are NOT part of this stage.

Deliver:

Alembic migration hardening the schema:
CHECK on registrations.status IN ('confirmed','waitlist','cancelled') and on notifications.status IN ('pending','sent','failed');
CHECK on registrations.email = lower(email);
server_default now() for created_at and queued_at on all tables. Update models.py to match.
Endpoints with Pydantic schemas (SPEC §6):
POST /api/events {title, description, starts_at, capacity} -> event + organizer_secret (generate with secrets.token_urlsafe). starts_at must be timezone-aware; reject past dates with 422.
GET /api/events and GET /api/events/{id} -> public data plus confirmed_count and waitlist_count (never expose organizer_secret).
POST /api/events/{id}/registrations {email} -> {status, ticket_code}. Email is trimmed and lowercased in the service layer, validate format.
GET /api/tickets/{code} -> status, position in waitlist (null if confirmed), event data.
Registration logic in services/registration.py, per SPEC §5:
one transaction; first statement is SELECT ... FROM events WHERE id=:id FOR UPDATE;
count confirmed; if < capacity -> confirmed, else waitlist (queued_at = now());
same email already active (confirmed/waitlist) -> return the existing registration, no new row;
same email with status cancelled -> reactivate the row, new status by the same rule, queued_at = now() (goes to the end of the queue), keep ticket_code;
ticket_code = secrets.token_urlsafe(9);
for a newly created or reactivated registration insert one notifications row (kind='ticket', dedup_key='ticket') in the same transaction, ON CONFLICT DO NOTHING. Sending is a later stage.
unknown event -> 404; event already started -> 409.
Tests (real concurrency, separate DB connections/threads, not sequential loops):
50 parallel registrations with different emails on capacity 10 -> exactly 10 confirmed, 40 waitlist, no errors;
2 parallel registrations for the last seat -> 1 confirmed, 1 waitlist;
same email registered 10 times in parallel -> exactly 1 row, 1 notification row;
email case/space variants (' A@X.com ') map to the same registration;
reactivation of a cancelled registration goes to the end of the queue (cancel via direct DB update in the test);
waitlist position in GET /api/tickets/{code} is correct;
the new CHECK constraints reject bad status and uppercase email.
Update README (new endpoints, how to run tests) and append a timestamped UTC entry to DEVLOG.md (real time, not invented; if you cannot know the time, write 'time not recorded').

Rules: one PR, small commits, PR description with what is done / verified by tests (include pytest output) / not done. Do not implement anything outside the list above.
