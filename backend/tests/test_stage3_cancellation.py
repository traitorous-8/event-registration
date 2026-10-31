import concurrent.futures
from datetime import datetime, timedelta, timezone
import threading
import pytest
from sqlalchemy.orm import Session

from backend.app.models import Event, Notification, Registration
from backend.tests.test_stage2_registration import create_event_via_api


def test_cancel_confirmed_promotes_earliest_waitlisted_and_notifies(client, test_engine, migrated_db, db_session):
    event = create_event_via_api(client, title="Cancel Promotion Event", capacity=1)
    event_id = event["id"]

    # reg1 confirmed
    r1 = client.post(f"/api/events/{event_id}/registrations", json={"email": "c1@test.com"}).json()
    t1 = r1["ticket_code"]

    # reg2 waitlist
    r2 = client.post(f"/api/events/{event_id}/registrations", json={"email": "w1@test.com"}).json()
    t2 = r2["ticket_code"]

    # reg3 waitlist
    r3 = client.post(f"/api/events/{event_id}/registrations", json={"email": "w2@test.com"}).json()
    t3 = r3["ticket_code"]

    # Cancel confirmed t1
    del_resp = client.delete(f"/api/tickets/{t1}")
    assert del_resp.status_code == 200
    assert del_resp.json() == {"status": "cancelled"}

    # Verify t1 is cancelled
    t1_info = client.get(f"/api/tickets/{t1}").json()
    assert t1_info["status"] == "cancelled"

    # Verify t2 is promoted to confirmed
    t2_info = client.get(f"/api/tickets/{t2}").json()
    assert t2_info["status"] == "confirmed"
    assert t2_info["position_in_waitlist"] is None

    # Verify t3 is still waitlist with position 1
    t3_info = client.get(f"/api/tickets/{t3}").json()
    assert t3_info["status"] == "waitlist"
    assert t3_info["position_in_waitlist"] == 1

    # Verify notifications
    reg2 = db_session.query(Registration).filter(Registration.ticket_code == t2).one()
    notifs = db_session.query(Notification).filter(Notification.registration_id == reg2.id).all()
    kinds = [n.kind for n in notifs]
    assert "ticket" in kinds
    assert "waitlist_promoted" in kinds
    promoted_notif = [n for n in notifs if n.kind == "waitlist_promoted"][0]
    assert promoted_notif.dedup_key == "promoted"
    assert promoted_notif.payload["ticket_code"] == t2
    assert promoted_notif.payload["event_title"] == "Cancel Promotion Event"


def test_double_cancel_same_ticket_sequential_and_parallel(client, test_engine, migrated_db, db_session):
    # 1. Sequential double cancel
    event_seq = create_event_via_api(client, title="Seq Double Cancel", capacity=1)
    e_seq_id = event_seq["id"]
    r1 = client.post(f"/api/events/{e_seq_id}/registrations", json={"email": "seq1@test.com"}).json()
    r2 = client.post(f"/api/events/{e_seq_id}/registrations", json={"email": "seq2@test.com"}).json()
    r3 = client.post(f"/api/events/{e_seq_id}/registrations", json={"email": "seq3@test.com"}).json()

    # First cancel
    del1 = client.delete(f"/api/tickets/{r1['ticket_code']}")
    assert del1.status_code == 200
    assert del1.json() == {"status": "cancelled"}

    # Second cancel (no-op)
    del2 = client.delete(f"/api/tickets/{r1['ticket_code']}")
    assert del2.status_code == 200
    assert del2.json() == {"status": "cancelled"}

    # r2 is confirmed, r3 remains waitlist (no second promotion!)
    assert client.get(f"/api/tickets/{r2['ticket_code']}").json()["status"] == "confirmed"
    assert client.get(f"/api/tickets/{r3['ticket_code']}").json()["status"] == "waitlist"

    # 2. Parallel double cancel (repeated across 10 iterations)
    for i in range(10):
        event = create_event_via_api(client, title=f"Parallel Double Cancel {i}", capacity=1)
        eid = event["id"]
        c1 = client.post(f"/api/events/{eid}/registrations", json={"email": f"c_{i}@test.com"}).json()
        w1 = client.post(f"/api/events/{eid}/registrations", json={"email": f"w1_{i}@test.com"}).json()
        w2 = client.post(f"/api/events/{eid}/registrations", json={"email": f"w2_{i}@test.com"}).json()

        code = c1["ticket_code"]
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            r = client.delete(f"/api/tickets/{code}")
            return r.status_code, r.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(worker)
            f2 = executor.submit(worker)
            res1 = f1.result()
            res2 = f2.result()

        assert res1[0] == 200 and res2[0] == 200
        assert res1[1] == {"status": "cancelled"}
        assert res2[1] == {"status": "cancelled"}

        # Exactly w1 was promoted, w2 remains waitlisted
        assert client.get(f"/api/tickets/{w1['ticket_code']}").json()["status"] == "confirmed"
        assert client.get(f"/api/tickets/{w2['ticket_code']}").json()["status"] == "waitlist"


def test_cancel_waitlisted_registration_no_promotion(client):
    event = create_event_via_api(client, title="Cancel Waitlist Event", capacity=1)
    eid = event["id"]

    r1 = client.post(f"/api/events/{eid}/registrations", json={"email": "c1@test.com"}).json()
    r2 = client.post(f"/api/events/{eid}/registrations", json={"email": "w1@test.com"}).json()
    r3 = client.post(f"/api/events/{eid}/registrations", json={"email": "w2@test.com"}).json()

    # Cancel waitlisted r2
    del_resp = client.delete(f"/api/tickets/{r2['ticket_code']}")
    assert del_resp.status_code == 200
    assert del_resp.json() == {"status": "cancelled"}

    # r1 stays confirmed, r3 stays waitlist at position 1
    assert client.get(f"/api/tickets/{r1['ticket_code']}").json()["status"] == "confirmed"
    t3_info = client.get(f"/api/tickets/{r3['ticket_code']}").json()
    assert t3_info["status"] == "waitlist"
    assert t3_info["position_in_waitlist"] == 1


def test_capacity_2_with_5_registered_cancel_both_in_parallel(client, test_engine, migrated_db, db_session):
    # Repeat to ensure rock-solid concurrency
    for iteration in range(5):
        event = create_event_via_api(client, title=f"Cap2 Parallel {iteration}", capacity=2)
        eid = event["id"]

        regs = []
        for j in range(5):
            r = client.post(f"/api/events/{eid}/registrations", json={"email": f"u_{iteration}_{j}@test.com"}).json()
            regs.append(r["ticket_code"])

        # regs[0], regs[1] are confirmed. regs[2], regs[3], regs[4] are waitlist.
        assert client.get(f"/api/tickets/{regs[0]}").json()["status"] == "confirmed"
        assert client.get(f"/api/tickets/{regs[1]}").json()["status"] == "confirmed"
        assert client.get(f"/api/tickets/{regs[2]}").json()["status"] == "waitlist"
        assert client.get(f"/api/tickets/{regs[3]}").json()["status"] == "waitlist"
        assert client.get(f"/api/tickets/{regs[4]}").json()["status"] == "waitlist"

        barrier = threading.Barrier(2)

        def worker(code):
            barrier.wait()
            r = client.delete(f"/api/tickets/{code}")
            return r.status_code, r.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(worker, regs[0])
            f2 = executor.submit(worker, regs[1])
            res1 = f1.result()
            res2 = f2.result()

        assert res1[0] == 200 and res2[0] == 200
        assert res1[1] == {"status": "cancelled"}
        assert res2[1] == {"status": "cancelled"}

        # exactly the first two waitlisted (regs[2] and regs[3]) are promoted
        assert client.get(f"/api/tickets/{regs[2]}").json()["status"] == "confirmed"
        assert client.get(f"/api/tickets/{regs[3]}").json()["status"] == "confirmed"
        t4_info = client.get(f"/api/tickets/{regs[4]}").json()
        assert t4_info["status"] == "waitlist"
        assert t4_info["position_in_waitlist"] == 1

        ev_info = client.get(f"/api/events/{eid}").json()
        assert ev_info["confirmed_count"] == 2
        assert ev_info["waitlist_count"] == 1


def test_parallel_mix_cancellations_and_new_registrations(client, test_engine, migrated_db):
    for iteration in range(5):
        event = create_event_via_api(client, title=f"Mix Event {iteration}", capacity=3)
        eid = event["id"]

        # Register initial 6 participants (3 confirmed, 3 waitlist)
        init_tickets = []
        for i in range(6):
            r = client.post(f"/api/events/{eid}/registrations", json={"email": f"init_{iteration}_{i}@test.com"}).json()
            init_tickets.append(r["ticket_code"])

        # We will have:
        # 3 cancellations of tickets (2 confirmed, 1 waitlisted)
        # 5 new registrations
        cancel_targets = [init_tickets[0], init_tickets[1], init_tickets[3]]
        new_emails = [f"new_{iteration}_{k}@test.com" for k in range(5)]

        total_actions = len(cancel_targets) + len(new_emails)
        barrier = threading.Barrier(total_actions)

        def cancel_worker(code):
            barrier.wait()
            r = client.delete(f"/api/tickets/{code}")
            return ("cancel", r.status_code)

        def reg_worker(email):
            barrier.wait()
            r = client.post(f"/api/events/{eid}/registrations", json={"email": email})
            return ("reg", r.status_code)

        with concurrent.futures.ThreadPoolExecutor(max_workers=total_actions) as executor:
            futures = []
            for c in cancel_targets:
                futures.append(executor.submit(cancel_worker, c))
            for em in new_emails:
                futures.append(executor.submit(reg_worker, em))

            results = [f.result() for f in futures]

        assert all(res[1] == 200 for res in results)

        # Invariant checks:
        ev_info = client.get(f"/api/events/{eid}").json()
        assert ev_info["confirmed_count"] <= 3

        # Invariant: no waitlisted person stays behind while a confirmed seat is free
        # Total active registrations remaining = (6 - 3) + 5 = 8
        # Since capacity is 3 and 8 >= 3, confirmed_count MUST be exactly 3, and waitlist_count MUST be 5.
        assert ev_info["confirmed_count"] == 3
        assert ev_info["waitlist_count"] == 5


def test_unknown_ticket_and_past_event(client, db_session):
    # Unknown ticket code -> 404
    r_unknown = client.delete("/api/tickets/non_existent_code_123")
    assert r_unknown.status_code == 404

    # Event already started -> 409
    event = create_event_via_api(client, title="Started Event", capacity=2, hours_ahead=1)
    eid = event["id"]
    reg = client.post(f"/api/events/{eid}/registrations", json={"email": "starter@test.com"}).json()
    t_code = reg["ticket_code"]

    # Manually move event.starts_at to the past in DB
    ev_db = db_session.query(Event).filter(Event.id == eid).one()
    ev_db.starts_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()

    # Try cancelling after started -> 409
    r_past = client.delete(f"/api/tickets/{t_code}")
    assert r_past.status_code == 409
    assert r_past.json()["detail"] == "Event has already started"
