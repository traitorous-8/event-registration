Read SPEC.md and AGENTS.md first and follow them, with ONE exception: do NOT edit DEVLOG.md in this task. Instead, add a final section "Proposed DEVLOG entry" to the PR description (date and time in UTC, what was done, decisions and why; if you cannot know the time write 'time not recorded'). Stages 1-5 are merged; start from the current main.

Task: Stage 6a, check-in and organizer view. SSE/live updates and frontend are NOT part of this task (they come in stage 6b).

Deliver:
1. POST /api/organizer/{secret}/checkin {ticket_code}.
   - Organizer secret compared with secrets.compare_digest; wrong secret -> 404.
   - One atomic statement: UPDATE registrations SET checked_in_at=now() WHERE ticket_code=:c AND event_id=:event AND status='confirmed' AND checked_in_at IS NULL RETURNING ... Never SELECT-then-UPDATE.
   - If no row was updated, find out why with a follow-up read: 404 if the code does not exist or belongs to another event, 409 if already checked in (include checked_in_at in the body), 422 if the registration is not 'confirmed' (waitlist or cancelled).
   - Success: 200 with email, ticket_code and checked_in_at.
2. DELETE /api/tickets/{code} on a confirmed registration that is already checked in returns 409 (a person who attended cannot cancel); the seat is not released and nobody is promoted. Waitlist and cancelled behaviour stays as in stage 3. Keep the lock order from stage 3 (event row first).
3. GET /api/organizer/{secret}: event data (never organizer_secret), counters {confirmed, waitlist, checked_in}, and the participants list (email, status, ticket_code, queued_at, checked_in_at) ordered by (queued_at, id). Wrong secret -> 404.
4. Tests (real concurrency with Barrier where relevant):
   - check-in success; same code twice -> 200 then 409; 20 parallel check-ins of one code -> exactly one 200 and 19 x 409; waitlist code -> 422; cancelled code -> 422; code of another event -> 404; unknown code -> 404; wrong secret -> 404;
   - cancel after check-in -> 409, seat not released, nobody promoted;
   - cancel of an already checked-in ticket racing with a promotion scenario: capacity 1, one confirmed checked-in + one waitlisted, cancel attempted -> 409 and the waitlisted stays waitlisted;
   - GET /api/organizer/{secret}: counters and participants correct after a mix of registrations, a cancellation with promotion and check-ins; checked_in counter correct; organizer_secret never appears in any response.
5. README: new endpoints, update "Current state" and "Not implemented yet" (SSE and frontend remain). Do not edit DEVLOG.md.

Rules: one PR, small commits. PR description sections: What is done / What is verified by tests (include pytest output) / What is not done / Proposed DEVLOG entry. State honestly whether you were able to run docker compose. Do not implement anything outside the lists above.
