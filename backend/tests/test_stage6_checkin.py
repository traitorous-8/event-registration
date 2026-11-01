import concurrent.futures
import threading
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models import Event, Registration
from backend.tests.test_stage2_registration import create_event_via_api


def test_checkin_success_and_second_time_conflict(client, db_session):
    event = create_event_via_api(client, title="Checkin Event", capacity=2)
    secret = event["organizer_secret"]
    eid = event["id"]

    reg_res = client.post(f"/api/events/{eid}/registrations", json={"email": "attendee@test.com"}).json()
    code = reg_res["ticket_code"]

    # First check-in -> 200
    res = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": code})
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "attendee@test.com"
    assert data["ticket_code"] == code
    assert data["checked_in_at"] is not None

    checked_in_time = data["checked_in_at"]

    # Second check-in -> 409 Conflict with checked_in_at in detail body
    res2 = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": code})
    assert res2.status_code == 409
    detail = res2.json()["detail"]
    assert "checked_in_at" in detail
    assert datetime.fromisoformat(detail["checked_in_at"]) == datetime.fromisoformat(checked_in_time)


def test_20_parallel_checkins_exactly_one_200_and_19_409(client, db_session):
    event = create_event_via_api(client, title="Parallel Checkin", capacity=2)
    secret = event["organizer_secret"]
    eid = event["id"]

    reg_res = client.post(f"/api/events/{eid}/registrations", json={"email": "speedy@test.com"}).json()
    code = reg_res["ticket_code"]

    barrier = threading.Barrier(20)

    def do_checkin():
        barrier.wait()
        return client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": code})

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(do_checkin) for _ in range(20)]
        results = [f.result() for f in futures]

    statuses = [r.status_code for r in results]
    assert statuses.count(200) == 1
    assert statuses.count(409) == 19

    # Verify checked_in counter on event
    org_res = client.get(f"/api/organizer/{secret}")
    assert org_res.status_code == 200
    assert org_res.json()["checked_in_count"] == 1


def test_checkin_validation_errors(client, db_session):
    # Event 1
    e1 = create_event_via_api(client, title="Event 1", capacity=1)
    s1 = e1["organizer_secret"]
    id1 = e1["id"]

    # Event 2
    e2 = create_event_via_api(client, title="Event 2", capacity=2)
    s2 = e2["organizer_secret"]
    id2 = e2["id"]

    # Confirmed in e1, waitlist in e1, confirmed in e2
    r_conf = client.post(f"/api/events/{id1}/registrations", json={"email": "c@e1.com"}).json()
    r_wait = client.post(f"/api/events/{id1}/registrations", json={"email": "w@e1.com"}).json()
    r_e2 = client.post(f"/api/events/{id2}/registrations", json={"email": "c@e2.com"}).json()

    # Cancelled in e2
    r_can = client.post(f"/api/events/{id2}/registrations", json={"email": "can@e2.com"}).json()
    client.delete(f"/api/tickets/{r_can['ticket_code']}")

    # 1. Wrong secret -> 404
    assert client.post("/api/organizer/wrong_secret_here/checkin", json={"ticket_code": r_conf["ticket_code"]}).status_code == 404

    # 2. Unknown code -> 404
    assert client.post(f"/api/organizer/{s1}/checkin", json={"ticket_code": "unknown_ticket_code"}).status_code == 404

    # 3. Code of another event -> 404
    assert client.post(f"/api/organizer/{s1}/checkin", json={"ticket_code": r_e2["ticket_code"]}).status_code == 404

    # 4. Waitlist code -> 422
    res_w = client.post(f"/api/organizer/{s1}/checkin", json={"ticket_code": r_wait["ticket_code"]})
    assert res_w.status_code == 422

    # 5. Cancelled code -> 422
    res_can = client.post(f"/api/organizer/{s2}/checkin", json={"ticket_code": r_can["ticket_code"]})
    assert res_can.status_code == 422


def test_cancel_after_checkin_returns_409_and_seat_preserved(client, db_session):
    # Rule: DELETE /api/tickets/{code} on confirmed registration already checked in returns 409
    event = create_event_via_api(client, title="Attended Event", capacity=1)
    secret = event["organizer_secret"]
    eid = event["id"]

    r1 = client.post(f"/api/events/{eid}/registrations", json={"email": "attended@test.com"}).json()
    r2 = client.post(f"/api/events/{eid}/registrations", json={"email": "waiting@test.com"}).json()
    code1 = r1["ticket_code"]
    code2 = r2["ticket_code"]

    # Check in r1
    checkin_res = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": code1})
    assert checkin_res.status_code == 200

    # Attempt cancel -> 409
    cancel_res = client.delete(f"/api/tickets/{code1}")
    assert cancel_res.status_code == 409

    # Seat must not be released; r2 is still waitlist
    ticket2 = client.get(f"/api/tickets/{code2}").json()
    assert ticket2["status"] == "waitlist"


def test_racing_checkin_and_cancel_with_waitlist(client, db_session):
    # Capacity 1: 1 confirmed checked in + 1 waitlisted. Cancel attempted -> 409 and waitlisted stays waitlisted.
    event = create_event_via_api(client, title="Race Event", capacity=1)
    secret = event["organizer_secret"]
    eid = event["id"]

    r1 = client.post(f"/api/events/{eid}/registrations", json={"email": "first@test.com"}).json()
    r2 = client.post(f"/api/events/{eid}/registrations", json={"email": "second@test.com"}).json()
    code1 = r1["ticket_code"]
    code2 = r2["ticket_code"]

    # Check-in first attendee
    ch_res = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": code1})
    assert ch_res.status_code == 200

    # Try cancel
    del_res = client.delete(f"/api/tickets/{code1}")
    assert del_res.status_code == 409

    # Verify second user was NOT promoted
    ticket_details = client.get(f"/api/tickets/{code2}").json()
    assert ticket_details["status"] == "waitlist"
    assert ticket_details["position_in_waitlist"] == 1


def test_get_organizer_counters_and_participants(client, db_session):
    event = create_event_via_api(client, title="Full Event", capacity=2)
    secret = event["organizer_secret"]
    eid = event["id"]

    # Wrong secret -> 404
    assert client.get("/api/organizer/invalid_secret").status_code == 404

    # Register 3 users: 2 confirmed, 1 waitlist
    r1 = client.post(f"/api/events/{eid}/registrations", json={"email": "u1@test.com"}).json()
    r2 = client.post(f"/api/events/{eid}/registrations", json={"email": "u2@test.com"}).json()
    r3 = client.post(f"/api/events/{eid}/registrations", json={"email": "u3@test.com"}).json()

    # Check in u1
    client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": r1["ticket_code"]})

    # Cancel u2 -> u3 gets promoted
    client.delete(f"/api/tickets/{r2['ticket_code']}")

    org_res = client.get(f"/api/organizer/{secret}")
    assert org_res.status_code == 200
    data = org_res.json()

    assert data["confirmed_count"] == 2
    assert data["waitlist_count"] == 0
    assert data["checked_in_count"] == 1
    assert "organizer_secret" not in data

    # Participants list ordered by (queued_at, id)
    participants = data["participants"]
    assert len(participants) == 3
    emails = [p["email"] for p in participants]
    assert set(emails) == {"u1@test.com", "u2@test.com", "u3@test.com"}

    u1_p = next(p for p in participants if p["email"] == "u1@test.com")
    assert u1_p["status"] == "confirmed"
    assert u1_p["checked_in_at"] is not None

    u2_p = next(p for p in participants if p["email"] == "u2@test.com")
    assert u2_p["status"] == "cancelled"

    u3_p = next(p for p in participants if p["email"] == "u3@test.com")
    assert u3_p["status"] == "confirmed"
