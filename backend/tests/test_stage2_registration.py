import concurrent.futures
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.models import Notification, Registration


def create_event_via_api(client, title="PyCon 2026", capacity=10, hours_ahead=24):
    starts_at = (datetime.now(timezone.utc) + timedelta(hours=hours_ahead)).isoformat()
    resp = client.post(
        "/api/events",
        json={
            "title": title,
            "description": "Python conference",
            "starts_at": starts_at,
            "capacity": capacity,
        },
    )
    assert resp.status_code == 201
    return resp.json()


def test_create_and_get_events(client):
    # Reject past starts_at
    past_starts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    resp = client.post(
        "/api/events",
        json={"title": "Past Event", "starts_at": past_starts, "capacity": 10},
    )
    assert resp.status_code == 422

    # Reject naive starts_at (no timezone offset)
    resp = client.post(
        "/api/events",
        json={"title": "Naive Event", "starts_at": "2026-12-01T12:00:00", "capacity": 10},
    )
    assert resp.status_code == 422

    # Create valid event
    event = create_event_via_api(client, capacity=5)
    assert "organizer_secret" in event
    assert event["confirmed_count"] == 0
    assert event["waitlist_count"] == 0

    # Get single event
    resp = client.get(f"/api/events/{event['id']}")
    assert resp.status_code == 200
    single = resp.json()
    assert single["id"] == event["id"]
    assert "organizer_secret" not in single

    # List events
    resp = client.get("/api/events")
    assert resp.status_code == 200
    lst = resp.json()
    assert len(lst) >= 1
    assert "organizer_secret" not in lst[0]


def test_50_parallel_registrations_capacity_10(client, test_engine, migrated_db):
    event = create_event_via_api(client, title="Parallel Event", capacity=10)
    event_id = event["id"]

    Session = sessionmaker(bind=test_engine)

    def worker(idx):
        # Separate DB session and client request per thread
        c = client
        email = f"user_{idx}@test.com"
        r = c.post(f"/api/events/{event_id}/registrations", json={"email": email})
        return r.status_code, r.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker, i) for i in range(50)]
        results = [f.result() for f in futures]

    statuses = [res[0] for res in results]
    assert all(status == 200 for status in statuses)

    reg_statuses = [res[1]["status"] for res in results]
    confirmed = [s for s in reg_statuses if s == "confirmed"]
    waitlist = [s for s in reg_statuses if s == "waitlist"]

    assert len(confirmed) == 10
    assert len(waitlist) == 40

    # Verify counts via GET /api/events/{id}
    resp = client.get(f"/api/events/{event_id}")
    assert resp.json()["confirmed_count"] == 10
    assert resp.json()["waitlist_count"] == 40


def test_2_parallel_registrations_last_seat(client, test_engine, migrated_db):
    event = create_event_via_api(client, title="Last Seat Event", capacity=1)
    event_id = event["id"]

    def worker(email):
        r = client.post(f"/api/events/{event_id}/registrations", json={"email": email})
        return r.status_code, r.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(worker, "userA@test.com")
        f2 = executor.submit(worker, "userB@test.com")
        res1 = f1.result()
        res2 = f2.result()

    assert res1[0] == 200 and res2[0] == 200
    st1 = res1[1]["status"]
    st2 = res2[1]["status"]

    assert sorted([st1, st2]) == ["confirmed", "waitlist"]


def test_same_email_registered_10_times_in_parallel(client, test_engine, migrated_db, db_session):
    event = create_event_via_api(client, title="Duplicate Email Event", capacity=10)
    event_id = event["id"]

    email = "same_email@test.com"

    def worker():
        r = client.post(f"/api/events/{event_id}/registrations", json={"email": email})
        return r.status_code, r.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker) for _ in range(10)]
        results = [f.result() for f in futures]

    assert all(res[0] == 200 for res in results)
    ticket_codes = {res[1]["ticket_code"] for res in results}
    assert len(ticket_codes) == 1  # exact same ticket returned for all 10 calls

    # Verify database has exactly 1 registration row and 1 notification row
    regs = db_session.query(Registration).filter(Registration.event_id == event_id).all()
    assert len(regs) == 1

    notifs = db_session.query(Notification).filter(Notification.registration_id == regs[0].id).all()
    assert len(notifs) == 1
    assert notifs[0].kind == "ticket"


def test_email_case_and_space_normalization(client, db_session):
    event = create_event_via_api(client, title="Normalization Event", capacity=10)
    event_id = event["id"]

    r1 = client.post(f"/api/events/{event_id}/registrations", json={"email": " A@X.com "})
    assert r1.status_code == 200

    r2 = client.post(f"/api/events/{event_id}/registrations", json={"email": "a@x.com"})
    assert r2.status_code == 200
    assert r1.json()["ticket_code"] == r2.json()["ticket_code"]

    regs = db_session.query(Registration).filter(Registration.event_id == event_id).all()
    assert len(regs) == 1
    assert regs[0].email == "a@x.com"


def test_reactivation_of_cancelled_goes_to_end_of_queue(client, db_session):
    event = create_event_via_api(client, title="Queue Event", capacity=1)
    event_id = event["id"]

    # reg1 gets confirmed
    r1 = client.post(f"/api/events/{event_id}/registrations", json={"email": "user1@test.com"})
    ticket1 = r1.json()["ticket_code"]

    # reg2 gets waitlist
    r2 = client.post(f"/api/events/{event_id}/registrations", json={"email": "user2@test.com"})
    ticket2 = r2.json()["ticket_code"]

    # reg3 gets waitlist
    r3 = client.post(f"/api/events/{event_id}/registrations", json={"email": "user3@test.com"})
    ticket3 = r3.json()["ticket_code"]

    # Cancel user2 via direct DB update
    reg2 = db_session.query(Registration).filter(Registration.ticket_code == ticket2).one()
    reg2.status = "cancelled"
    db_session.commit()

    # Re-register user2
    r2_new = client.post(f"/api/events/{event_id}/registrations", json={"email": "user2@test.com"})
    assert r2_new.status_code == 200
    assert r2_new.json()["ticket_code"] == ticket2
    assert r2_new.json()["status"] == "waitlist"

    # Verify waitlist positions
    t3_info = client.get(f"/api/tickets/{ticket3}").json()
    t2_info = client.get(f"/api/tickets/{ticket2}").json()

    assert t3_info["position_in_waitlist"] == 1
    assert t2_info["position_in_waitlist"] == 2


def test_ticket_endpoint_and_waitlist_position(client):
    event = create_event_via_api(client, title="Ticket Info Event", capacity=1)
    event_id = event["id"]

    # Confirmed
    r1 = client.post(f"/api/events/{event_id}/registrations", json={"email": "c1@test.com"})
    ticket1 = r1.json()["ticket_code"]

    t1_resp = client.get(f"/api/tickets/{ticket1}")
    assert t1_resp.status_code == 200
    t1_data = t1_resp.json()
    assert t1_data["status"] == "confirmed"
    assert t1_data["position_in_waitlist"] is None
    assert t1_data["event"]["id"] == event_id

    # Waitlist 1
    r2 = client.post(f"/api/events/{event_id}/registrations", json={"email": "w1@test.com"})
    ticket2 = r2.json()["ticket_code"]
    t2_resp = client.get(f"/api/tickets/{ticket2}")
    assert t2_resp.json()["position_in_waitlist"] == 1

    # Waitlist 2
    r3 = client.post(f"/api/events/{event_id}/registrations", json={"email": "w2@test.com"})
    ticket3 = r3.json()["ticket_code"]
    t3_resp = client.get(f"/api/tickets/{ticket3}")
    assert t3_resp.json()["position_in_waitlist"] == 2
