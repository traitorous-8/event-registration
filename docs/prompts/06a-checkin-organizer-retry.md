Read SPEC.md and AGENTS.md first and follow them, with ONE exception: do NOT edit DEVLOG.md. Instead, write a final section "Proposed DEVLOG entry" in the PR description (UTC date and time; if you cannot know the time write 'time not recorded').

CONTEXT. A previous attempt at stage 6a deleted existing stage 5 code (scheduler.py, templates, a migration, tests, the scheduler service in docker-compose.yml, PATCH /api/organizer/{secret}) and was reverted. This is a retry. Your work must be strictly additive.

STEP 0, before writing any code:
- Run `git fetch origin` and create a NEW branch from the latest origin/main (not from any older jules-* branch).
- Run the full test suite and report the exact number of passing tests (expected: 35).
- Confirm these exist and note that you must not delete or rewrite them: backend/app/workers/scheduler.py, backend/app/workers/outbox.py, backend/app/workers/templates.py, backend/app/api/organizer.py (it already contains PATCH /api/organizer/{secret}), backend/alembic/versions/f900bca402e9_allow_skipped_in_notification_status.py, backend/tests/test_stage5_scheduler.py, the scheduler service in docker-compose.yml. If any of them is missing, STOP and report; do not recreate them.

TASK: stage 6a, check-in and organizer view. SSE and frontend are NOT in scope.

Deliver, by ADDING to existing files, never replacing them:
1. In backend/app/api/organizer.py, ADD (keep PATCH untouched):
   - POST /api/organizer/{secret}/checkin {ticket_code}: secret via secrets.compare_digest, wrong secret -> 404. One atomic statement: UPDATE registrations SET checked_in_at=now() WHERE ticket_code=:c AND event_id=:event AND status='confirmed' AND checked_in_at IS NULL RETURNING ... Never SELECT-then-UPDATE. If no row was updated, find out why with a follow-up read: 404 (code unknown or belongs to another event), 409 (already checked in, include checked_in_at), 422 (not 'confirmed'). Success: 200 with email, ticket_code, checked_in_at.
   - GET /api/organizer/{secret}: event data (never organizer_secret), counters {confirmed, waitlist, checked_in}, participants list (email, status, ticket_code, queued_at, checked_in_at) ordered by (queued_at, id). Wrong secret -> 404.
2. In the cancel logic of services/registration.py: cancelling a confirmed registration that is already checked in returns 409; the seat is not released and nobody is promoted. Keep the stage 3 lock order (event row first). Waitlist and cancelled behaviour unchanged.
3. Tests in a NEW file backend/tests/test_stage6_checkin.py (real concurrency with Barrier where relevant): check-in success; same code twice -> 200 then 409; 20 parallel check-ins of one code -> exactly one 200 and 19 x 409; waitlist code -> 422; cancelled code -> 422; code of another event -> 404; unknown code -> 404; wrong secret -> 404; cancel after check-in -> 409, seat not released, waitlisted person stays waitlisted; GET organizer counters and participants correct after a mix of registrations, a cancellation with promotion and check-ins; organizer_secret never appears in any response.
4. README: ADD the new endpoints and update "Current state". Do not remove existing README content.

HARD RULES:
- Do not delete, rename or rewrite any existing file. Allowed edits to existing files are additions plus the minimal change in item 2.
- Do not create new Alembic migrations (none are needed).
- Do not touch docker-compose.yml.
- Before opening the PR run `git diff --stat origin/main...HEAD` and paste the output into the PR description. It must show no deleted files and no large deletions in existing files; if it does, fix your branch first.
- The full test suite must pass and the number of tests must be 35 plus your new tests. Paste the pytest output into the PR description.
- Write the PR description yourself with sections: What is done / What is verified by tests / What is not done / git diff --stat / Proposed DEVLOG entry. Open it as a new pull request from your new branch.
