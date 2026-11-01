Read SPEC.md and AGENTS.md first and follow them, with ONE exception: do NOT edit DEVLOG.md in this task. Instead, add a final section "Proposed DEVLOG entry" to the PR description (date and time in UTC, what was done, decisions and why; if you cannot know the time write 'time not recorded'). Stages 1-4 are merged; start from the current main.

Task: Stage 5, scheduler for reminders and event rescheduling (SPEC §5). Check-in, organizer views, SSE and frontend are NOT part of this stage.

Deliver:
1. Alembic migration: extend the CHECK on notifications.status to also allow 'skipped'. Update models.py.
2. backend/app/workers/scheduler.py: a separate process, a loop with SCHEDULER_POLL_SECONDS (default 30, add to config.py and .env.example). The tick logic lives in a function run_tick(session, now) so tests can inject the time.
   - For every event with starts_at > now and starts_at - now <= 24h, for every registration with status 'confirmed', insert one notification (kind='reminder_24h', dedup_key=<event starts_at as ISO UTC string>, payload with event data) with INSERT ... ON CONFLICT DO NOTHING. One reminder per registration per event date, regardless of how many ticks run.
   - Waitlist and cancelled registrations get no reminder. A waitlisted person promoted to confirmed inside the 24h window gets the reminder on the next tick.
   - Events that already started get nothing. If the scheduler was down, the first tick after restart creates reminders that are still due (event not started yet), never for past events.
   - Safe with two schedulers running at once (rely on the unique key, no extra locks needed).
3. PATCH /api/organizer/{secret} {starts_at}: reschedule.
   - Find the event by organizer_secret using secrets.compare_digest; wrong secret -> 404 (do not reveal that the event exists).
   - New starts_at must be timezone-aware and in the future, else 422. Same value as current -> 200, no changes, no notifications.
   - In one transaction: lock the event row FOR UPDATE, update starts_at, mark pending 'reminder_24h' notifications of this event whose dedup_key differs from the new date as 'skipped', and insert one notification (kind='event_rescheduled', dedup_key=<new starts_at ISO>, payload with old and new times) for every 'confirmed' and 'waitlist' registration, ON CONFLICT DO NOTHING.
   - Response: the updated public event data (never expose organizer_secret in this response).
4. Outbox worker changes (backend/app/workers/outbox.py): before sending a 'reminder_24h' or 'event_rescheduled' notification re-check the registration; if it is 'cancelled' mark the notification 'skipped' and do not send. Add Russian templates in workers/templates.py: 'reminder_24h' (event title, start time in UTC and Asia/Almaty, ticket code, the registration status) and 'event_rescheduled' (title, old and new time in UTC and Asia/Almaty). Distinct subjects.
5. docker-compose.yml: new service "scheduler" (same image as backend, command python -m backend.app.workers.scheduler, depends_on postgres healthy), same environment.
6. Tests (backend/tests/test_stage5_scheduler.py), real concurrency where relevant, time injected through run_tick(now):
   - event 23h away, 3 confirmed + 2 waitlist: one tick -> exactly 3 reminder notifications (confirmed only); 10 more ticks -> still 3;
   - two ticks in parallel (threads, Barrier) -> still exactly 3;
   - event 25h away -> no reminders; same event with now moved forward to 23h -> reminders created;
   - a waitlisted registration promoted by a cancellation inside the 24h window gets its reminder on the next tick, exactly once;
   - event already started -> nothing created;
   - reschedule: confirmed + waitlist get exactly one 'event_rescheduled' each, cancelled get none; repeating the same PATCH creates no new notifications; wrong secret -> 404; past date -> 422;
   - reschedule after a reminder was already sent: a new reminder for the new date is created and sent once when the new date enters the 24h window (the old one is not re-sent); pending reminders for the old date become 'skipped';
   - end to end with the real in-process SMTP fixture from stage 4: register 2 people, reschedule, run the outbox worker, exactly 2 'event_rescheduled' emails captured; then tick + worker -> exactly 1 reminder each when the event is within 24h.
   - a registration cancelled after its reminder was created but before sending -> the worker marks it 'skipped', no email.
7. README: scheduler description, the PATCH endpoint, new env vars; update "Current state" and "Not implemented yet". Do not edit DEVLOG.md.

Rules: one PR, small commits. PR description sections: What is done / What is verified by tests (include pytest output) / What is not done / Proposed DEVLOG entry. State honestly whether you were able to run docker compose with the scheduler service; do not claim it works if you could not run it. Do not implement anything outside the lists above.
