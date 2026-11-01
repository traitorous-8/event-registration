import concurrent.futures
from datetime import datetime, timedelta, timezone
import threading
import pytest

from backend.app.models import Event, Registration
from backend.tests.test_stage2_registration import create_event_via_api


def test_checkin_success(client):
    event = create_event_via_api(client, title="Check-in Success Event", capacity=2)
    secret = event["organizer_secret"]

    reg = client.post(f"/api/events/{event['id']}/registrations", json={"email": "alice@test.com"}).json()
    ticket_code = reg["ticket_code"]

    resp = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": ticket_code})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "alice@test.com"
    assert data["ticket_code"] == ticket_code
    assert data["checked_in_at"] is not None

    # Verify organizer_secret does not leak in response
    assert "organizer_secret" not in data


def test_checkin_same_code_twice_sequential(client):
    event = create_event_via_api(client, title="Check-in Twice Event", capacity=2)
    secret = event["organizer_secret"]

    reg = client.post(f"/api/events/{event['id']}/registrations", json={"email": "bob@test.com"}).json()
    ticket_code = reg["ticket_code"]

    resp1 = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": ticket_code})
    assert resp1.status_code == 200
    checked_in_at = resp1.json()["checked_in_at"]

    resp2 = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": ticket_code})
    assert resp2.status_code == 409
    assert "already checked in" in resp2.json()["detail"]
    # Verify timestamp or ISO representation is included
    assert checked_in_at[:19] in resp2.json()["detail"]


def test_20_parallel_checkins_single_code(client, test_engine, migrated_db):
    event = create_event_via_api(client, title="Parallel Check-in Event", capacity=5)
    secret = event["organizer_secret"]

    reg = client.post(f"/api/events/{event['id']}/registrations", json={"email": "parallel@test.com"}).json()
    ticket_code = reg["ticket_code"]

    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()
        r = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": ticket_code})
        return r.status_code, r.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker) for _ in range(20)]
        results = [f.result() for f in futures]

    statuses = [res[0] for res in results]
    assert statuses.count(200) == 1
    assert statuses.count(409) == 19

    # All 409 responses contain the checked_in_at timestamp
    success_res = [res[1] for res in results if res[0] == 200][0]
    checked_in_at = success_res["checked_in_at"]
    for res in results:
        if res[0] == 409:
            assert "already checked in" in res[1]["detail"]
            assert checked_in_at[:19] in res[1]["detail"]


def test_checkin_waitlist_code_returns_422(client):
    event = create_event_via_api(client, title="Waitlist Check-in Event", capacity=1)
    secret = event["organizer_secret"]

    client.post(f"/api/events/{event['id']}/registrations", json={"email": "c@test.com"}).json()
    w_reg = client.post(f"/api/events/{event['id']}/registrations", json={"email": "w@test.com"}).json()
    waitlist_code = w_reg["ticket_code"]

    resp = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": waitlist_code})
    assert resp.status_code == 422
    assert "waitlist" in resp.json()["detail"]


def test_checkin_cancelled_code_returns_422(client):
    event = create_event_via_api(client, title="Cancelled Check-in Event", capacity=2)
    secret = event["organizer_secret"]

    reg = client.post(f"/api/events/{event['id']}/registrations", json={"email": "canc@test.com"}).json()
    ticket_code = reg["ticket_code"]

    # Cancel ticket
    del_resp = client.delete(f"/api/tickets/{ticket_code}")
    assert del_resp.status_code == 200

    resp = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": ticket_code})
    assert resp.status_code == 422
    assert "cancelled" in resp.json()["detail"]


def test_checkin_code_of_another_event_returns_404(client):
    event1 = create_event_via_api(client, title="Event 1", capacity=2)
    event2 = create_event_via_api(client, title="Event 2", capacity=2)

    reg1 = client.post(f"/api/events/{event1['id']}/registrations", json={"email": "ev1@test.com"}).json()
    ticket_code1 = reg1["ticket_code"]

    # Check-in ticket from event 1 using secret of event 2 -> 404
    resp = client.post(f"/api/organizer/{event2['organizer_secret']}/checkin", json={"ticket_code": ticket_code1})
    assert resp.status_code == 404


def test_checkin_unknown_code_returns_404(client):
    event = create_event_via_api(client, title="Unknown Code Event", capacity=2)
    resp = client.post(f"/api/organizer/{event['organizer_secret']}/checkin", json={"ticket_code": "unknown_code_999"})
    assert resp.status_code == 404


def test_checkin_wrong_secret_returns_404(client):
    event = create_event_via_api(client, title="Wrong Secret Event", capacity=2)
    reg = client.post(f"/api/events/{event['id']}/registrations", json={"email": "ws@test.com"}).json()

    resp = client.post("/api/organizer/totally_invalid_secret_abc/checkin", json={"ticket_code": reg["ticket_code"]})
    assert resp.status_code == 404


def test_cancel_after_checkin_returns_409(client):
    event = create_event_via_api(client, title="Cancel Checked-in Event", capacity=1)
    secret = event["organizer_secret"]

    # Confirmed participant
    r1 = client.post(f"/api/events/{event['id']}/registrations", json={"email": "c1@test.com"}).json()
    t1 = r1["ticket_code"]

    # Waitlisted participant
    r2 = client.post(f"/api/events/{event['id']}/registrations", json={"email": "w1@test.com"}).json()
    t2 = r2["ticket_code"]

    # Check-in t1
    checkin_resp = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": t1})
    assert checkin_resp.status_code == 200

    # Attempt to cancel t1
    cancel_resp = client.delete(f"/api/tickets/{t1}")
    assert cancel_resp.status_code == 409
    assert "already checked in" in cancel_resp.json()["detail"]

    # Verify t1 is still confirmed and checked in
    t1_info = client.get(f"/api/tickets/{t1}").json()
    assert t1_info["status"] == "confirmed"

    # Verify t2 is STILL waitlisted (not promoted, seat was not released)
    t2_info = client.get(f"/api/tickets/{t2}").json()
    assert t2_info["status"] == "waitlist"
    assert t2_info["position_in_waitlist"] == 1

    # Verify event counts
    ev_info = client.get(f"/api/events/{event['id']}").json()
    assert ev_info["confirmed_count"] == 1
    assert ev_info["waitlist_count"] == 1


def test_organizer_get_view_counters_and_participants(client):
    event = create_event_via_api(client, title="Organizer View Event", capacity=2)
    secret = event["organizer_secret"]
    eid = event["id"]

    # 1. Register 4 users: 2 confirmed (u1, u2), 2 waitlist (u3, u4)
    r1 = client.post(f"/api/events/{eid}/registrations", json={"email": "u1@test.com"}).json()
    r2 = client.post(f"/api/events/{eid}/registrations", json={"email": "u2@test.com"}).json()
    r3 = client.post(f"/api/events/{eid}/registrations", json={"email": "u3@test.com"}).json()
    r4 = client.post(f"/api/events/{eid}/registrations", json={"email": "u4@test.com"}).json()

    # 2. Cancel u1 (confirmed) -> u3 gets promoted to confirmed
    del_resp = client.delete(f"/api/tickets/{r1['ticket_code']}")
    assert del_resp.status_code == 200

    # 3. Check-in u2 (confirmed)
    ch2 = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": r2["ticket_code"]})
    assert ch2.status_code == 200

    # 4. Check-in u3 (promoted confirmed)
    ch3 = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": r3["ticket_code"]})
    assert ch3.status_code == 200

    # 5. GET /api/organizer/{secret}
    view_resp = client.get(f"/api/organizer/{secret}")
    assert view_resp.status_code == 200
    data = view_resp.json()

    # Check event details
    assert data["event"]["id"] == eid
    assert data["event"]["title"] == "Organizer View Event"
    assert data["event"]["capacity"] == 2
    assert "organizer_secret" not in data["event"]
    assert "organizer_secret" not in data

    # Check counters
    # Confirmed: u2 and u3 = 2
    # Waitlist: u4 = 1
    # Checked-in: u2 and u3 = 2
    assert data["counters"]["confirmed"] == 2
    assert data["counters"]["waitlist"] == 1
    assert data["counters"]["checked_in"] == 2

    # Check participants list ordering by (queued_at, id)
    participants = data["participants"]
    assert len(participants) == 4
    emails = [p["email"] for p in participants]
    assert emails == ["u1@test.com", "u2@test.com", "u3@test.com", "u4@test.com"]

    # Verify participant fields and statuses
    p_map = {p["email"]: p for p in participants}
    assert p_map["u1@test.com"]["status"] == "cancelled"
    assert p_map["u1@test.com"]["checked_in_at"] is None

    assert p_map["u2@test.com"]["status"] == "confirmed"
    assert p_map["u2@test.com"]["checked_in_at"] is not None

    assert p_map["u3@test.com"]["status"] == "confirmed"
    assert p_map["u3@test.com"]["checked_in_at"] is not None

    assert p_map["u4@test.com"]["status"] == "waitlist"
    assert p_map["u4@test.com"]["checked_in_at"] is None

    # Verify invalid secret on GET /api/organizer/{secret} returns 404
    resp_wrong = client.get("/api/organizer/invalid_organizer_secret_xyz")
    assert resp_wrong.status_code == 404


def test_organizer_secret_never_appears_in_responses(client):
    event = create_event_via_api(client, title="Secret Privacy Event", capacity=2)
    secret = event["organizer_secret"]

    reg = client.post(f"/api/events/{event['id']}/registrations", json={"email": "p@test.com"}).json()
    t_code = reg["ticket_code"]

    # Check-in response
    ch_resp = client.post(f"/api/organizer/{secret}/checkin", json={"ticket_code": t_code})
    assert ch_resp.status_code == 200
    assert secret not in ch_resp.text

    # Organizer view response
    view_resp = client.get(f"/api/organizer/{secret}")
    assert view_resp.status_code == 200
    assert secret not in view_resp.text
