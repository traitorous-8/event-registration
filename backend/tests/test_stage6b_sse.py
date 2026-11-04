import asyncio
from datetime import datetime, timedelta, timezone
import json
import socket
import threading
import time
import httpx
import pytest
import uvicorn

from backend.app.config import settings
from backend.app.events_bus import bus
from backend.app.main import app


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def sse_server():
    port = get_free_port()
    old_heartbeat = settings.sse_heartbeat_seconds
    settings.sse_heartbeat_seconds = 1.0

    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config=config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"

    for _ in range(50):
        try:
            with httpx.Client(timeout=1.0) as client:
                res = client.get(f"{base_url}/health")
                if res.status_code == 200:
                    break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("Test server failed to start")

    yield base_url

    server.should_exit = True
    thread.join(timeout=3.0)
    settings.sse_heartbeat_seconds = old_heartbeat


def parse_sse_events_from_iter(line_iter, max_events=1, timeout_secs=5.0):
    events = []
    current_event = None
    current_data = []
    start_time = time.time()

    while len(events) < max_events:
        if time.time() - start_time > timeout_secs:
            break
        try:
            line = next(line_iter)
        except StopIteration:
            break

        line = line.strip("\r\n")
        if not line:
            if current_event is not None or current_data:
                events.append({
                    "event": current_event,
                    "data": "\n".join(current_data),
                })
                current_event = None
                current_data = []
            continue

        if line.startswith(":"):
            events.append({"event": "comment", "data": line[1:].strip()})
        elif line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current_data.append(line.split(":", 1)[1].strip())

    return events


def test_sse_404_for_unknown_event_secret_code(sse_server, migrated_db):
    client = httpx.Client(base_url=sse_server, timeout=5.0)

    # Unknown event stream
    res = client.get("/api/events/99999/stream")
    assert res.status_code == 404

    # Unknown organizer stream
    res = client.get("/api/organizer/invalidsecret123/stream")
    assert res.status_code == 404

    # Unknown ticket stream
    res = client.get("/api/tickets/invalidcode123/stream")
    assert res.status_code == 404


def test_sse_initial_snapshot_and_two_clients_public_stream(sse_server, migrated_db):
    client = httpx.Client(base_url=sse_server, timeout=5.0)
    future_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    ev_res = client.post(
        "/api/events",
        json={"title": "SSE Conf", "starts_at": future_time, "capacity": 1},
    )
    assert ev_res.status_code == 201
    event_id = ev_res.json()["id"]

    client1 = httpx.Client(base_url=sse_server, timeout=5.0)
    ctx1 = client1.stream("GET", f"/api/events/{event_id}/stream")
    res1 = ctx1.__enter__()
    iter1 = res1.iter_lines()

    # Client 1 initial snapshot
    ev1 = parse_sse_events_from_iter(iter1, max_events=1, timeout_secs=3.0)
    assert len(ev1) == 1
    assert ev1[0]["event"] == "counts"
    assert json.loads(ev1[0]["data"]) == {"confirmed": 0, "waitlist": 0}

    client2 = httpx.Client(base_url=sse_server, timeout=5.0)
    ctx2 = client2.stream("GET", f"/api/events/{event_id}/stream")
    res2 = ctx2.__enter__()
    iter2 = res2.iter_lines()

    # Client 2 initial snapshot
    ev2 = parse_sse_events_from_iter(iter2, max_events=1, timeout_secs=3.0)
    assert len(ev2) == 1
    assert ev2[0]["event"] == "counts"
    assert json.loads(ev2[0]["data"]) == {"confirmed": 0, "waitlist": 0}

    # Register user
    reg_res = client.post(f"/api/events/{event_id}/registrations", json={"email": "u1@example.com"})
    assert reg_res.status_code == 200

    # Both clients receive updated counts
    updated1 = parse_sse_events_from_iter(iter1, max_events=1, timeout_secs=3.0)
    assert len(updated1) == 1
    assert updated1[0]["event"] == "counts"
    assert json.loads(updated1[0]["data"]) == {"confirmed": 1, "waitlist": 0}

    updated2 = parse_sse_events_from_iter(iter2, max_events=1, timeout_secs=3.0)
    assert len(updated2) == 1
    assert updated2[0]["event"] == "counts"
    assert json.loads(updated2[0]["data"]) == {"confirmed": 1, "waitlist": 0}

    ctx1.__exit__(None, None, None)
    ctx2.__exit__(None, None, None)
    client1.close()
    client2.close()


def test_sse_organizer_stream_counts_and_participants_after_checkin(sse_server, migrated_db):
    client = httpx.Client(base_url=sse_server, timeout=5.0)
    future_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    ev_res = client.post(
        "/api/events",
        json={"title": "Checkin SSE Test", "starts_at": future_time, "capacity": 2},
    )
    assert ev_res.status_code == 201
    ev_data = ev_res.json()
    event_id = ev_data["id"]
    secret = ev_data["organizer_secret"]

    # Register 1 participant
    reg_res = client.post(f"/api/events/{event_id}/registrations", json={"email": "attendee@example.com"})
    ticket_code = reg_res.json()["ticket_code"]

    # Connect organizer stream
    org_client = httpx.Client(base_url=sse_server, timeout=5.0)
    ctx = org_client.stream("GET", f"/api/organizer/{secret}/stream")
    res = ctx.__enter__()
    lines = res.iter_lines()

    # Initial snapshot sends both 'counts' and 'participants'
    initial_events = parse_sse_events_from_iter(lines, max_events=2, timeout_secs=3.0)
    assert len(initial_events) == 2
    assert initial_events[0]["event"] == "counts"
    counts_data = json.loads(initial_events[0]["data"])
    assert counts_data == {"confirmed": 1, "waitlist": 0, "checked_in": 0}

    assert initial_events[1]["event"] == "participants"
    participants_data = json.loads(initial_events[1]["data"])
    assert len(participants_data) == 1
    assert participants_data[0]["ticket_code"] == ticket_code
    assert participants_data[0]["checked_in_at"] is None

    # Check in
    checkin_res = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": ticket_code})
    assert checkin_res.status_code == 200

    # Stream should receive updated 'counts' and 'participants'
    update_events = parse_sse_events_from_iter(lines, max_events=2, timeout_secs=3.0)
    assert len(update_events) == 2
    assert update_events[0]["event"] == "counts"
    assert json.loads(update_events[0]["data"])["checked_in"] == 1

    assert update_events[1]["event"] == "participants"
    updated_parts = json.loads(update_events[1]["data"])
    assert updated_parts[0]["checked_in_at"] is not None

    ctx.__exit__(None, None, None)
    org_client.close()


def test_sse_ticket_stream_waitlist_promoted(sse_server, migrated_db):
    client = httpx.Client(base_url=sse_server, timeout=5.0)
    future_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    ev_res = client.post(
        "/api/events",
        json={"title": "Promotion SSE Test", "starts_at": future_time, "capacity": 1},
    )
    event_id = ev_res.json()["id"]

    # Register first (confirmed)
    r1 = client.post(f"/api/events/{event_id}/registrations", json={"email": "first@example.com"})
    ticket_confirmed = r1.json()["ticket_code"]

    # Register second (waitlisted)
    r2 = client.post(f"/api/events/{event_id}/registrations", json={"email": "second@example.com"})
    ticket_waitlisted = r2.json()["ticket_code"]
    assert r2.json()["status"] == "waitlist"

    # Connect to waitlisted ticket stream
    t_client = httpx.Client(base_url=sse_server, timeout=5.0)
    ctx = t_client.stream("GET", f"/api/tickets/{ticket_waitlisted}/stream")
    res = ctx.__enter__()
    lines = res.iter_lines()

    # Initial snapshot
    init_ev = parse_sse_events_from_iter(lines, max_events=1, timeout_secs=3.0)
    assert len(init_ev) == 1
    assert init_ev[0]["event"] == "ticket"
    t_data = json.loads(init_ev[0]["data"])
    assert t_data["status"] == "waitlist"
    assert t_data["position_in_waitlist"] == 1

    # Confirmed participant cancels
    cancel_res = client.delete(f"/api/tickets/{ticket_confirmed}")
    assert cancel_res.status_code == 200

    # Waitlisted ticket stream receives promotion update
    promoted_ev = parse_sse_events_from_iter(lines, max_events=1, timeout_secs=3.0)
    assert len(promoted_ev) == 1
    assert promoted_ev[0]["event"] == "ticket"
    promoted_data = json.loads(promoted_ev[0]["data"])
    assert promoted_data["status"] == "confirmed"
    assert promoted_data["position_in_waitlist"] is None

    ctx.__exit__(None, None, None)
    t_client.close()


def test_sse_heartbeat_line_when_idle(sse_server, migrated_db):
    client = httpx.Client(base_url=sse_server, timeout=5.0)
    future_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    ev_res = client.post(
        "/api/events",
        json={"title": "Heartbeat Test", "starts_at": future_time, "capacity": 5},
    )
    event_id = ev_res.json()["id"]

    h_client = httpx.Client(base_url=sse_server, timeout=5.0)
    ctx = h_client.stream("GET", f"/api/events/{event_id}/stream")
    res = ctx.__enter__()
    lines = res.iter_lines()

    # 1st event is initial snapshot
    init_ev = parse_sse_events_from_iter(lines, max_events=1, timeout_secs=3.0)
    assert len(init_ev) == 1
    assert init_ev[0]["event"] == "counts"

    # Wait for heartbeat line (timeout is 1.0s)
    hb_ev = parse_sse_events_from_iter(lines, max_events=1, timeout_secs=3.0)
    assert len(hb_ev) == 1
    assert hb_ev[0]["event"] == "comment"
    assert hb_ev[0]["data"] == "ping"

    ctx.__exit__(None, None, None)
    h_client.close()


def test_failed_operations_publish_nothing(sse_server, migrated_db):
    client = httpx.Client(base_url=sse_server, timeout=5.0)
    future_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    ev_res = client.post(
        "/api/events",
        json={"title": "Failed Op Test", "starts_at": future_time, "capacity": 2},
    )
    event_id = ev_res.json()["id"]
    secret = ev_res.json()["organizer_secret"]

    # Register and check in
    reg = client.post(f"/api/events/{event_id}/registrations", json={"email": "fail@example.com"}).json()
    code = reg["ticket_code"]
    client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": code})

    # Subscribe to event stream
    test_client = httpx.Client(base_url=sse_server, timeout=5.0)
    ctx = test_client.stream("GET", f"/api/events/{event_id}/stream")
    res = ctx.__enter__()
    lines = res.iter_lines()

    # Initial snapshot
    parse_sse_events_from_iter(lines, max_events=1, timeout_secs=3.0)

    # 1. Failed cancel after checkin (returns 409)
    res_409 = client.delete(f"/api/tickets/{code}")
    assert res_409.status_code == 409

    # 2. Failed checkin wrong secret (returns 404)
    res_wrong_sec = client.post("/api/organizer/wrongsecret999/checkin", json={"ticket_code": code})
    assert res_wrong_sec.status_code == 404

    # 3. Failed cancel unknown ticket (returns 404)
    res_unknown_ticket = client.delete("/api/tickets/unknowncode")
    assert res_unknown_ticket.status_code == 404

    # Confirm stream received no counts event (only heartbeat ping could arrive)
    idle_events = parse_sse_events_from_iter(lines, max_events=1, timeout_secs=2.0)
    assert len(idle_events) == 1
    assert idle_events[0]["event"] == "comment"  # ping heartbeat, not counts

    ctx.__exit__(None, None, None)
    test_client.close()


def test_disconnected_client_leaves_no_subscriber(sse_server, migrated_db):
    client = httpx.Client(base_url=sse_server, timeout=5.0)
    future_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    ev_res = client.post(
        "/api/events",
        json={"title": "Cleanup Test", "starts_at": future_time, "capacity": 5},
    )
    event_id = ev_res.json()["id"]

    sub_client = httpx.Client(base_url=sse_server, timeout=5.0)
    ctx = sub_client.stream("GET", f"/api/events/{event_id}/stream")
    res = ctx.__enter__()
    lines = res.iter_lines()

    # Read initial event
    parse_sse_events_from_iter(lines, max_events=1, timeout_secs=3.0)
    assert event_id in bus._subscribers
    assert len(bus._subscribers[event_id]) >= 1

    # Disconnect client
    ctx.__exit__(None, None, None)
    sub_client.close()

    # Trigger a publish so server loop detects disconnect and executes finally
    for _ in range(25):
        bus.publish(event_id)
        time.sleep(0.1)
        if event_id not in bus._subscribers or len(bus._subscribers[event_id]) == 0:
            break

    assert event_id not in bus._subscribers or len(bus._subscribers[event_id]) == 0


def test_public_stream_never_contains_email_ticket_or_secret(sse_server, migrated_db):
    client = httpx.Client(base_url=sse_server, timeout=5.0)
    future_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    ev_res = client.post(
        "/api/events",
        json={"title": "Privacy Test", "starts_at": future_time, "capacity": 5},
    )
    event_id = ev_res.json()["id"]
    secret = ev_res.json()["organizer_secret"]

    email = "supersecretuser@example.com"
    r = client.post(f"/api/events/{event_id}/registrations", json={"email": email}).json()
    ticket_code = r["ticket_code"]

    # Connect to public stream
    pub_client = httpx.Client(base_url=sse_server, timeout=5.0)
    with pub_client.stream("GET", f"/api/events/{event_id}/stream") as stream:
        raw_chunks = []
        start = time.time()
        for line in stream.iter_lines():
            raw_chunks.append(line)
            if time.time() - start > 1.5:
                break

    full_payload = "\n".join(raw_chunks)
    assert email not in full_payload
    assert ticket_code not in full_payload
    assert secret not in full_payload
