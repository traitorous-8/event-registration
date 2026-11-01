Read SPEC.md and AGENTS.md first and follow them, with ONE exception: do NOT edit DEVLOG.md in this task. Instead, add a final section "Proposed DEVLOG entry" to the PR description (date and time in UTC, what was done, decisions and why; if you cannot know the time write 'time not recorded'). Stages 1-5 are merged; start from the current main.

Task: Stage 6, check-in, organizer view and live updates over SSE (SPEC §5-7). Frontend is NOT part of this stage.

Deliver:
1. POST /api/organizer/{secret}/checkin {ticket_code}.
   - Organizer secret compared with secrets.compare_digest; wrong secret -> 404.
   - One atomic statement: UPDATE registrations SET checked_in_at=now() WHERE ticket_code=:c AND event_id=:event AND status='confirmed' AND checked_in_at IS NULL RETURNING ... Never SELECT-then-UPDATE.
   - No row updated: 404 if the code does not exist or belongs to another event, 409 if already checked in (include checked_in_at), 422 if the registration is not 'confirmed' (waitlist or cancelled).
   - Success: 200 with the participant's email, ticket_code and checked_in_at.
2. Rule: DELETE /api/tickets/{code} on a confirmed registration that is already checked in returns 409 (a person who attended cannot cancel). Waitlist and cancelled behaviour stays as in stage 3.
3. GET /api/organizer/{secret}: event data (without organizer_secret), counters {confirmed, waitlist, checked_in}, and the participants list (email, status, ticket_code, queued_at, checked_in_at) ordered by (queued_at, id). Wrong secret -> 404.
4. Live updates, SSE (text/event-stream), in-process bus in backend/app/events_bus.py.
   - Streams: GET /api/events/{id}/stream (public: counters {confirmed, waitlist}), GET /api/organizer/{secret}/stream (counters {confirmed, waitlist, checked_in}), GET /api/tickets/{code}/stream (status and position_in_waitlist of that one ticket). Unknown event, secret or code -> 404 before the stream starts.
   - On connect send an immediate snapshot event, then updates as they happen. Message format: "event: <name>\ndata: <json>\n\n", names 'counts', 'participants' (organizer stream only: sent when the participants list changes) and 'ticket'. Heartbeat comment line (": ping") every 15 seconds. Always send full snapshots, not deltas, so a lost message does not matter; use a bounded queue per subscriber that drops the oldest message when full.
   - Publish AFTER commit, never inside the transaction. Publishing is triggered by: registration (new, reactivated), cancellation including promotion from the waitlist, check-in, reschedule is not needed. Operations that fail or roll back (404, 409, 422) must publish nothing.
   - Thread-safety: the sync endpoints run in a threadpool while SSE handlers run on the event loop. The bus must be thread-safe (publish from any thread via loop.call_soon_threadsafe or equivalent), clean up the subscriber when the client disconnects, and not leak queues.
   - Public streams must never contain emails, ticket codes of others, or the organizer secret.
   - Backend must run a single uvicorn worker (no --workers option); say so in the README.
5. Tests (real concurrency, Barrier where relevant):
   - check-in: success; same code twice -> 200 then 409; 20 parallel check-ins of one code -> exactly one 200 and 19 409; waitlist code -> 422; cancelled code -> 422; code of another event -> 404; unknown code -> 404; wrong secret -> 404; checked_in counter correct;
   - cancel after check-in -> 409 and the seat is not released;
   - GET /api/organizer/{secret}: counters and participants correct after a mix of registrations, cancellation with promotion and check-ins;
   - bus unit tests: subscribe, publish from another thread, receive; bounded queue drops oldest; unsubscribe cleans up;
   - SSE integration test with a real server: run uvicorn in a background thread on a free port and read streams with httpx streaming. Two clients on /api/events/{id}/stream both receive the new counters after one registration; the organizer stream receives 'counts' and 'participants' after a check-in; the ticket stream of a waitlisted person receives status 'confirmed' and position null after the confirmed person cancels; the initial snapshot arrives on connect;
   - a failed operation (e.g. registration on an event that already started, wrong organizer secret) publishes nothing;
   - a disconnected client does not leave a subscriber behind.
6. README: new endpoints, SSE usage with a curl example (curl -N), the single-worker note, update "Current state" and "Not implemented yet". Do not edit DEVLOG.md.

Rules: one PR, small commits. PR description sections: What is done / What is verified by tests (include pytest output) / What is not done / Proposed DEVLOG entry. State honestly whether you were able to run docker compose; do not claim it works if you could not run it. Do not implement anything outside the lists above.
