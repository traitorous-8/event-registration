Read SPEC.md and AGENTS.md first and follow them, with ONE exception: do NOT edit DEVLOG.md. Instead write a final section "Proposed DEVLOG entry" in the PR description (UTC date and time; if you cannot know the time write 'time not recorded').

CONTEXT. Two earlier attempts at stage 6 went wrong: one was too large and did not finish, one deleted existing stage 5 code. Stage 6b is strictly ADDITIVE: it must not delete, rename or rewrite existing behaviour.

STEP 0, before writing any code:
- Run `git fetch origin` and create a NEW branch from the latest origin/main.
- Run the full test suite and report the exact number of passing tests (expected: 46).
- Confirm these exist and must not be deleted or rewritten: backend/app/workers/scheduler.py, outbox.py, templates.py, backend/app/api/organizer.py (it contains PATCH, POST checkin and GET organizer), backend/alembic/versions/f900bca402e9_allow_skipped_in_notification_status.py, backend/tests/test_stage5_scheduler.py, backend/tests/test_stage6_checkin.py, the scheduler service in docker-compose.yml. If any is missing, STOP and report; do not recreate them.

TASK: stage 6b, live updates over SSE (SPEC §7). The frontend is NOT in scope.

Deliver:
1. backend/app/events_bus.py: an in-process pub/sub keyed by event_id.
   - Subscribers are asyncio queues bound to the event loop they were created in. publish(event_id) may be called from ANY thread (the sync endpoints run in a threadpool) and must deliver safely with loop.call_soon_threadsafe.
   - Bounded queue per subscriber (maxsize 100); when full, drop the OLDEST message. Always send full snapshots, never deltas, so a dropped message does not matter.
   - unsubscribe removes the subscriber and its queue; no leaks.
2. Three SSE endpoints (media type text/event-stream), added to the existing routers:
   - GET /api/events/{id}/stream (public): event 'counts' with {confirmed, waitlist}.
   - GET /api/organizer/{secret}/stream: event 'counts' with {confirmed, waitlist, checked_in} and event 'participants' with the same participants list as GET /api/organizer/{secret}. Secret via secrets.compare_digest; wrong secret -> 404 before the stream starts.
   - GET /api/tickets/{code}/stream: event 'ticket' with {status, position_in_waitlist} of that one ticket only.
   - Unknown event, secret or code -> 404 before the stream starts.
   - On connect send an immediate snapshot, then a new snapshot after every relevant change. Message format: "event: <name>\ndata: <json>\n\n". Heartbeat comment line ": ping\n\n" every 15 seconds (make the interval configurable via SSE_HEARTBEAT_SECONDS, default 15, so tests can use 1).
   - DB reads for snapshots must not block the event loop (use starlette.concurrency.run_in_threadpool or equivalent) and must use their own short-lived session.
   - Disconnect handling: stop and unsubscribe when the client disconnects (check request.is_disconnected and use try/finally).
   - Public streams must never contain emails, other people's ticket codes or the organizer secret.
3. Publishing, strictly AFTER commit, never inside a transaction: call bus.publish(event_id) from the API layer after the service function has returned successfully. Triggers: new registration, reactivated registration, cancellation (including the promotion of a waitlisted person, the promoted person's ticket stream must update), check-in, and PATCH reschedule (organizer stream only needs it to stay consistent). Failed operations (404, 409, 422, rollback) must publish nothing. Do not change the service-layer transaction logic or lock order.
4. README: document the three streams with a curl example (curl -N), the event names, and the single-worker limitation (the bus is in-process, so uvicorn must run with one worker; the compose file already does). Update "Current state" and "Not implemented yet" (only the frontend remains). Keep all existing README content. Add SSE_HEARTBEAT_SECONDS to .env.example and config.py.
5. Tests in NEW files only (backend/tests/test_stage6b_bus.py and backend/tests/test_stage6b_sse.py):
   - bus unit tests: subscribe then publish from another thread and receive; bounded queue drops the oldest when full; unsubscribe cleans up; publishing with no subscribers is a no-op;
   - SSE integration with a REAL server: start uvicorn in a background thread on a free port against the test database and read the streams with httpx streaming. Cases: the initial snapshot arrives on connect; two clients on the public stream both receive new counts after one registration; the organizer stream receives 'counts' and 'participants' after a check-in; the ticket stream of a waitlisted person receives status 'confirmed' and position null after the confirmed person cancels; a heartbeat line arrives when idle (SSE_HEARTBEAT_SECONDS=1); 404 for unknown event, secret and code before streaming;
   - failed operations publish nothing (registration on an event that already started, wrong organizer secret, cancel after check-in);
   - a disconnected client leaves no subscriber behind;
   - the public streams never contain an email, a ticket code or the secret.
   Every stream read in tests needs a timeout so a failure cannot hang the test suite.

HARD RULES:
- Do not delete, rename or rewrite any existing file. Edits to existing files are additions plus the small publish calls in the API layer.
- Do not create Alembic migrations (none are needed). Do not touch docker-compose.yml.
- Before opening the PR run `git diff --stat origin/main...HEAD` and paste it into the PR description. It must show no deleted files and no large deletions in existing files; if it does, fix your branch first.
- The full suite must pass: 46 existing tests plus your new ones. Paste the pytest output into the PR description.
- PR description sections: What is done / What is verified by tests / What is not done / git diff --stat / Proposed DEVLOG entry. State honestly whether you were able to run docker compose; do not claim it works if you could not run it. Open the PR from your new branch.
- Do not implement anything outside the lists above.
