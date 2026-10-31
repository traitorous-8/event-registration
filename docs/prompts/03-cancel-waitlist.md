Read SPEC.md and AGENTS.md first and follow them. Stages 1 and 2 are merged; start from the current main.

Task: Stage 3. Part A hardens the stage 2 tests and docs, part B adds cancellation with waitlist promotion. Do A first, then B. Sending email, scheduler, check-in and SSE are NOT part of this stage.

PART A. Hardening

A1. Race tests must be truly concurrent. In backend/tests/test_stage2_registration.py use threading.Barrier so that all workers send their request at the same moment. Repeat the "2 parallel registrations for the last seat" test in a loop of 20 iterations (new event each time) and require the invariant every time. Remove the unused sessionmaker/Session variables, unused imports and the misleading "separate DB session" comment. A2. Check backend/tests/conftest.py: the get_db dependency must give every API request its own connection/session. If it is overridden with one shared session, fix it so concurrent requests do not share a connection. A3. Prove the race tests have teeth: temporarily remove .with_for_update() in services/registration.py, run the race tests, confirm they FAIL, then restore it. Report in the PR description exactly which tests failed (names and assertion messages). If they do not fail, strengthen them until they do. Do not commit the removal. A4. README: add a "Known limitations" section: the ticket code is returned in the registration response and there is no email confirmation (demo simplification; in a real product it would only be sent by email); the live-update bus is in-process so one uvicorn worker only; the outbox has a small window between sending an email and marking it sent (at-least-once, deduplicated by the unique key). Add a "Current state" section listing what works and what is not implemented yet, kept honest and updated each stage.

PART B. Cancellation and promotion (SPEC §5)

B1. DELETE /api/tickets/{code}, idempotent, returns {"status": "cancelled"}.

Unknown code -> 404. Event already started -> 409.
Lock order rule: always lock the event row first. Read the registration's event_id, then SELECT ... FROM events WHERE id=:id FOR UPDATE, and only then re-read the registration status (it may have changed while waiting for the lock).
status confirmed -> set cancelled, then in the SAME transaction promote the first waitlist registration of that event ordered by (queued_at, id) to confirmed and insert one notification (kind='waitlist_promoted', dedup_key='promoted', payload with ticket_code and event title) with ON CONFLICT DO NOTHING.
status waitlist -> set cancelled, no promotion.
status cancelled -> 200 no-op, no second promotion. B2. Put the logic in services/registration.py (cancel_registration), keep HTTP concerns in the api layer. B3. Tests (real concurrency with Barrier, repeat race tests several times):
cancel a confirmed registration -> the earliest waitlisted becomes confirmed, exactly one waitlist_promoted notification, remaining waitlist order unchanged;
double cancel of the same ticket (sequential and parallel) -> exactly one promotion;
cancel a waitlisted registration -> nobody is promoted;
capacity 2 with 5 registered: cancel both confirmed in parallel -> exactly the first two waitlisted are promoted, confirmed_count == capacity;
parallel mix of cancellations and new registrations on one event -> confirmed_count never exceeds capacity and no waitlisted person stays behind while a confirmed seat is free;
cancelled registration followed by re-registration still goes to the end of the queue (existing test must keep passing);
404 for unknown code, 409 after the event started. B4. Update README (new endpoint) and append timestamped UTC entries to DEVLOG.md (real time; if you cannot know the time, write 'time not recorded').

Rules: one PR, small commits. PR description must have the sections: What is done / What is verified by tests (include pytest output and the A3 failure report) / What is not done. Do not implement anything outside the lists above.
