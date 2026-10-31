Read SPEC.md and AGENTS.md first and follow them. Stages 1-3 are merged; start from the current main.

Task: Stage 4, outbox worker and email delivery through SMTP (MailHog). Scheduler/reminders, check-in, SSE and frontend are NOT part of this stage.

Deliver:
1. backend/app/workers/outbox.py: a worker process that delivers rows from the notifications table (SPEC §5).
   - Loop: in one transaction select up to N rows with status='pending' ordered by id using FOR UPDATE SKIP LOCKED; for each row send the email via smtplib to SMTP_HOST:SMTP_PORT; on success set status='sent', sent_at=now(); on failure attempts+1 and keep it pending, after 5 failed attempts set status='failed'. Commit per message. Locks are held while sending; that is intended, it is what prevents two workers from sending the same row.
   - The recipient is the email of the related registration. Sender comes from a new env var SMTP_FROM (default noreply@events.local). Polling interval from OUTBOX_POLL_SECONDS (default 2) and batch size from OUTBOX_BATCH_SIZE (default 20). Add all new vars to .env.example and config.py.
   - Graceful handling of SMTP being down: the worker must not crash, it logs the error and retries on the next iteration.
   - Unknown notification kind -> mark failed with a log message, never crash.
2. Email content (plain text, Russian), built in one place (workers/templates.py):
   - kind 'ticket': event title, start time shown in UTC and Asia/Almaty, the status (confirmed or waitlist) at the time of sending, the ticket code, and a line explaining that DELETE /api/tickets/{code} cancels the registration.
   - kind 'waitlist_promoted': you got a seat, event title, start time, ticket code.
   - Subject lines distinguish the two kinds.
3. docker-compose.yml: a new service "worker" using the same image as backend, command python -m backend.app.workers.outbox, depends_on postgres healthy and mailhog, same environment. The backend service must not start the worker.
4. Tests (backend/tests/test_stage4_outbox.py), using a real in-process SMTP server such as aiosmtpd as a fixture that captures messages (add it to requirements with a pinned version), not mocks of smtplib:
   - a pending 'ticket' notification is delivered once: exactly one captured message to the right address, row becomes sent with sent_at set;
   - running two worker iterations in parallel (threads, Barrier) over the same pending rows delivers each exactly once;
   - SMTP failure: attempts increases, status stays pending; after 5 failures status becomes failed; after SMTP recovers a pending row is delivered;
   - end to end: register through the API on a capacity-1 event with two emails, cancel the first ticket, run the worker, and check that three messages were captured: ticket for a, ticket for b, waitlist_promoted for b, each exactly once;
   - re-running the worker with nothing pending sends nothing;
   - unknown kind -> failed, worker keeps running.
5. README: how to run the worker, where to see emails (http://localhost:8025), new env vars, update "Current state" and remove email delivery from the "Not implemented" list. Append timestamped UTC entries to DEVLOG.md (real time; if unknown write 'time not recorded').

Rules: one PR, small commits. PR description sections: What is done / What is verified by tests (include pytest output) / What is not done. Also state honestly in the PR description whether you were able to run docker compose with the worker service; do not claim it works if you could not run it. Do not implement anything outside the lists above.
