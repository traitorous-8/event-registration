Read SPEC.md and AGENTS.md first and follow them, with ONE exception: do NOT edit DEVLOG.md. Instead write a final section "Proposed DEVLOG entry" in the PR description (UTC date and time; if you cannot know the time write 'time not recorded').

CONTEXT. Earlier stage 6 attempts went wrong (one too large, one deleted existing code). Stage 7 is strictly ADDITIVE and deliberately lean: functional first, minimal styling.

STEP 0, before writing any code:
- Run `git fetch origin` and create a NEW branch from the latest origin/main.
- Run the full backend test suite and report the exact number of passing tests (expected: 58).
- Confirm these exist and must not be deleted or rewritten: backend/app/workers/scheduler.py, outbox.py, templates.py, backend/app/events_bus.py, backend/app/api/organizer.py, events.py, tickets.py, backend/alembic/versions/f900bca402e9_allow_skipped_in_notification_status.py, all tests under backend/tests, and the scheduler and worker services in docker-compose.yml. If any is missing, STOP and report; do not recreate them.

TASK: stage 7, React frontend in a NEW top-level folder frontend/. Do NOT change anything under backend/.

Stack: Vite + React 18 + react-router-dom, plain CSS (no UI libraries), vitest + @testing-library/react for tests. Pin all versions in package.json and commit package-lock.json. The frontend talks to the existing REST and SSE API over the network (separate client, separate server). Use relative URLs (/api/...), never a hardcoded host.

Pages and behaviour (all text in Russian):
1. "/" Event list (GET /api/events) with counters, plus a create form (title, description, date-time, capacity; inputs use the browser's local time zone and are sent as ISO 8601 with offset). After creating show the organizer link /organizer/{secret} prominently with a copy button and a warning that it is shown only once and grants organizer access. Show server validation errors (422) readably.
2. "/events/:id" Public event page: title, description, start time in the user's local time, live counters {confirmed, waitlist} via EventSource on /api/events/{id}/stream, registration form (email) -> POST /api/events/{id}/registrations. Show the result: status (confirmed or waitlist) and a link to /ticket/{code}. 404 and 409 (event already started) shown as clear messages. Remember the user's tickets for this event in localStorage (per-viewer convenience only; every read and write in try/catch; the page must work when storage is empty).
3. "/ticket/:code" Ticket page: status and position_in_waitlist, live via EventSource on /api/tickets/{code}/stream, cancel button -> DELETE /api/tickets/{code} with a confirm dialog. Show 409 ("already checked in and cannot be cancelled") and 404 clearly. Status labels in Russian (confirmed, waitlist, cancelled).
4. "/organizer/:secret" Organizer page: counters {confirmed, waitlist, checked_in} and the participants table (email, status, ticket code, queued_at, checked_in_at) live via EventSource on /api/organizer/{secret}/stream; check-in form (ticket code) -> POST /api/organizer/{secret}/checkin showing 200, 404, 409 (already checked in, show the time) and 422 distinctly; reschedule form -> PATCH /api/organizer/{secret} {starts_at}. Wrong secret (404) shows an "access denied / not found" screen.
5. A reusable hook useEventSource(url, handlers) with: automatic reconnect with backoff (EventSource already retries; handle the error state and show a small "нет связи" / "live" indicator), cleanup on unmount, and re-fetching a full snapshot is NOT needed because the server sends full snapshots on connect. Without a browser reload, two open tabs must show the same data (this is a hard requirement of the task).
6. A small api client module (fetch wrapper) that returns {ok, status, data} and never throws on HTTP errors.

Serving and Docker:
7. frontend/Dockerfile: multi-stage build (node to build, nginx to serve the static files). frontend/nginx.conf: serve the SPA with fallback to index.html; proxy /api/ to http://backend:8000 with proxy_http_version 1.1, proxy_buffering off, proxy_cache off, proxy_read_timeout 3600s and an empty Connection header so SSE streams work through the proxy.
8. docker-compose.yml: ADD a "frontend" service (build ./frontend, ports "3000:80", depends_on backend). Do not modify or remove any existing service.
9. Vite dev server proxy config for /api to http://localhost:8000 for local development.

Tests (vitest, in frontend/): the api client (success, 404/409/422 without throwing); useEventSource with a mocked EventSource (receives snapshots, cleanup on unmount, error indicator); EventListPage create flow shows the organizer link; EventPage registration shows confirmed/waitlist and updates counters on a live message; TicketPage cancel flow and the 409 message; OrganizerPage check-in results for 200/409/422 and the access-denied screen. `npm test` and `npm run build` must pass.

CI: ADD a second job "frontend" to .github/workflows/ci.yml (npm ci, npm test, npm run build). Do not change the existing backend job.

README: ADD a "Frontend" section (how to run with docker compose at http://localhost:3000, how to run locally with npm, where the pages are, the proxy/SSE note) and update "Current state" and "Not implemented yet". Keep all existing README content.

HARD RULES:
- Do not delete, rename or rewrite any existing file. Edits to existing files are additions only (docker-compose.yml, ci.yml, README.md).
- Do not touch backend/ at all.
- Before opening the PR run `git diff --stat origin/main...HEAD` and paste it into the PR description. It must show no deleted files and no deletions in existing files; if it does, fix your branch first.
- Run the backend suite again at the end (must still be 58 passed) and the frontend tests; paste both outputs into the PR description.
- PR description sections: What is done / What is verified by tests / What is not done / git diff --stat / Proposed DEVLOG entry. State honestly whether you could run docker compose and the frontend container; do not claim it works if you could not.
- Keep the UI plain and functional. Do not implement anything outside the lists above.
