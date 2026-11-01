import concurrent.futures
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from backend.app.models import Event, Notification, Registration
from backend.app.workers.outbox import process_outbox_batch
from backend.app.workers.scheduler import run_tick
from backend.tests.test_stage2_registration import create_event_via_api
from backend.tests.test_stage4_outbox import smtp_server


def test_event_23h_away_creates_reminders_and_subsequent_ticks_are_idempotent(client, db_session):
    # Event 23h away, 3 confirmed + 2 waitlist:
    # one tick -> exactly 3 reminder notifications (confirmed only);
    # 10 more ticks -> still 3.
    base_now = datetime.now(timezone.utc) + timedelta(days=20)
    event_start = (base_now + timedelta(hours=23)).replace(microsecond=0)

    event_payload = {
        "title": "Tech Conference",
        "description": "Tech conference in 23h",
        "starts_at": event_start.isoformat(),
        "capacity": 3,
    }
    r = client.post("/api/events", json=event_payload)
    assert r.status_code == 201
    event = r.json()
    eid = event["id"]

    for i in range(5):
        reg_r = client.post(f"/api/events/{eid}/registrations", json={"email": f"user{i}@test.com"})
        assert reg_r.status_code == 200

    # Before tick, only 5 "ticket" notifications exist
    assert db_session.query(Notification).filter(Notification.kind == "reminder_24h").count() == 0

    # First tick with injected time base_now
    created = run_tick(db_session, base_now)
    assert created == 3

    reminder_notifs = db_session.query(Notification).filter(Notification.kind == "reminder_24h").all()
    assert len(reminder_notifs) == 3
    for n in reminder_notifs:
        assert n.status == "pending"
        assert n.dedup_key == event_start.isoformat()
        assert n.payload["event_title"] == "Tech Conference"
        assert n.payload["starts_at"] == event_start.isoformat()

    # 10 more ticks with same 'base_now'
    for _ in range(10):
        c = run_tick(db_session, base_now)
        assert c == 0

    assert db_session.query(Notification).filter(Notification.kind == "reminder_24h").count() == 3


def test_two_ticks_in_parallel_create_exactly_confirmed_count(client, db_session, test_engine):
    # Two ticks in parallel (threads, Barrier) -> still exactly 3
    base_now = datetime.now(timezone.utc) + timedelta(days=20)
    event_start = (base_now + timedelta(hours=20)).replace(microsecond=0)

    event_payload = {
        "title": "Parallel Tick Event",
        "starts_at": event_start.isoformat(),
        "capacity": 3,
    }
    r = client.post("/api/events", json=event_payload)
    assert r.status_code == 201
    eid = r.json()["id"]

    for i in range(5):
        client.post(f"/api/events/{eid}/registrations", json={"email": f"parallel_user{i}@test.com"})

    SessionLocalTest = sessionmaker(bind=test_engine)
    barrier = threading.Barrier(2)

    def tick_worker():
        barrier.wait()
        sess = SessionLocalTest()
        try:
            return run_tick(sess, base_now)
        finally:
            sess.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(tick_worker)
        f2 = executor.submit(tick_worker)
        c1 = f1.result()
        c2 = f2.result()

    assert c1 + c2 == 3
    assert db_session.query(Notification).filter(Notification.kind == "reminder_24h").count() == 3


def test_event_25h_away_no_reminders_until_entering_24h_window(client, db_session):
    # event 25h away -> no reminders;
    # same event with now moved forward to 23h -> reminders created
    base_now = datetime.now(timezone.utc) + timedelta(days=20)
    event_start = (base_now + timedelta(hours=25)).replace(microsecond=0)

    r = client.post(
        "/api/events",
        json={"title": "Future Event", "starts_at": event_start.isoformat(), "capacity": 2},
    )
    assert r.status_code == 201
    eid = r.json()["id"]
    client.post(f"/api/events/{eid}/registrations", json={"email": "alice@test.com"})
    client.post(f"/api/events/{eid}/registrations", json={"email": "bob@test.com"})

    # Tick at 25h away -> 0 reminders created
    created_25h = run_tick(db_session, base_now)
    assert created_25h == 0
    assert db_session.query(Notification).filter(Notification.kind == "reminder_24h").count() == 0

    # Advance now by 2 hours -> event is now 23h away
    now_forward = base_now + timedelta(hours=2)
    created_23h = run_tick(db_session, now_forward)
    assert created_23h == 2
    assert db_session.query(Notification).filter(Notification.kind == "reminder_24h").count() == 2


def test_waitlist_promoted_inside_24h_window_gets_reminder_on_next_tick(client, db_session):
    # A waitlisted registration promoted by a cancellation inside the 24h window
    # gets its reminder on the next tick, exactly once
    base_now = datetime.now(timezone.utc) + timedelta(days=20)
    event_start = (base_now + timedelta(hours=10)).replace(microsecond=0)

    r = client.post(
        "/api/events",
        json={"title": "Promotion Event", "starts_at": event_start.isoformat(), "capacity": 1},
    )
    assert r.status_code == 201
    eid = r.json()["id"]

    r1 = client.post(f"/api/events/{eid}/registrations", json={"email": "first@test.com"}).json()
    r2 = client.post(f"/api/events/{eid}/registrations", json={"email": "second@test.com"}).json()

    assert r1["status"] == "confirmed"
    assert r2["status"] == "waitlist"

    # First tick -> only r1 gets reminder
    run_tick(db_session, base_now)
    reminders = db_session.query(Notification).filter(Notification.kind == "reminder_24h").all()
    assert len(reminders) == 1
    reg1 = db_session.query(Registration).filter(Registration.email == "first@test.com").one()
    assert reminders[0].registration_id == reg1.id

    # Now cancel first registration inside the 24h window -> second gets promoted to confirmed
    del_r = client.delete(f"/api/tickets/{r1['ticket_code']}")
    assert del_r.status_code == 200

    reg2 = db_session.query(Registration).filter(Registration.email == "second@test.com").one()
    assert reg2.status == "confirmed"

    # Next tick -> second gets reminder
    created_second = run_tick(db_session, base_now)
    assert created_second == 1

    reminders = db_session.query(Notification).filter(Notification.kind == "reminder_24h").all()
    assert len(reminders) == 2
    reg2_reminders = [r for r in reminders if r.registration_id == reg2.id]
    assert len(reg2_reminders) == 1

    # Further tick -> no new reminders
    assert run_tick(db_session, base_now) == 0
    assert db_session.query(Notification).filter(Notification.kind == "reminder_24h").count() == 2


def test_event_already_started_creates_nothing(client, db_session):
    # Event already started -> nothing created.
    # If scheduler was down, first tick after restart creates reminders still due (not started yet),
    # never for past events.
    now = datetime.now(timezone.utc)
    event_start = now - timedelta(minutes=5)

    # Insert started event directly into db (since API forbids past starts_at)
    event = Event(
        title="Started Event",
        starts_at=event_start,
        capacity=5,
        organizer_secret="secret_started",
    )
    db_session.add(event)
    db_session.flush()

    reg = Registration(
        event_id=event.id,
        email="attendee@test.com",
        ticket_code="started_ticket",
        status="confirmed",
    )
    db_session.add(reg)
    db_session.commit()

    created = run_tick(db_session, now)
    assert created == 0
    assert db_session.query(Notification).filter(Notification.kind == "reminder_24h").count() == 0


def test_reschedule_endpoint_validation_and_idempotency(client, db_session):
    now = datetime.now(timezone.utc)
    future_start = now + timedelta(days=5)

    r = client.post(
        "/api/events",
        json={"title": "Reschedule Event", "starts_at": future_start.isoformat(), "capacity": 2},
    )
    event = r.json()
    secret = event["organizer_secret"]
    eid = event["id"]

    # 3 registrations: 2 confirmed, 1 waitlist, 1 cancelled
    r1 = client.post(f"/api/events/{eid}/registrations", json={"email": "c1@test.com"}).json()
    r2 = client.post(f"/api/events/{eid}/registrations", json={"email": "c2@test.com"}).json()
    r3 = client.post(f"/api/events/{eid}/registrations", json={"email": "w1@test.com"}).json()
    r4 = client.post(f"/api/events/{eid}/registrations", json={"email": "can@test.com"}).json()
    client.delete(f"/api/tickets/{r4['ticket_code']}")

    # Check wrong secret -> 404
    bad_res = client.patch(f"/api/organizer/invalid_secret_123", json={"starts_at": (now + timedelta(days=10)).isoformat()})
    assert bad_res.status_code == 404

    # Past date -> 422
    past_date = (now - timedelta(days=1)).isoformat()
    past_res = client.patch(f"/api/organizer/{secret}", json={"starts_at": past_date})
    assert past_res.status_code == 422

    # Naive date (no timezone) -> 422
    naive_res = client.patch(f"/api/organizer/{secret}", json={"starts_at": "2026-08-01T12:00:00"})
    assert naive_res.status_code == 422

    # Valid reschedule
    new_start = (now + timedelta(days=10)).replace(microsecond=0)
    patch_res = client.patch(f"/api/organizer/{secret}", json={"starts_at": new_start.isoformat()})
    assert patch_res.status_code == 200
    res_data = patch_res.json()
    assert "organizer_secret" not in res_data
    assert res_data["id"] == eid

    # Confirmed + waitlist get exactly one 'event_rescheduled' each, cancelled get none
    resched_notifs = db_session.query(Notification).filter(Notification.kind == "event_rescheduled").all()
    assert len(resched_notifs) == 3
    notif_reg_ids = {n.registration_id for n in resched_notifs}

    c1_reg = db_session.query(Registration).filter(Registration.email == "c1@test.com").one()
    c2_reg = db_session.query(Registration).filter(Registration.email == "c2@test.com").one()
    w1_reg = db_session.query(Registration).filter(Registration.email == "w1@test.com").one()
    can_reg = db_session.query(Registration).filter(Registration.email == "can@test.com").one()

    assert c1_reg.id in notif_reg_ids
    assert c2_reg.id in notif_reg_ids
    assert w1_reg.id in notif_reg_ids
    assert can_reg.id not in notif_reg_ids

    # Repeating the same PATCH creates no new notifications
    repeat_res = client.patch(f"/api/organizer/{secret}", json={"starts_at": new_start.isoformat()})
    assert repeat_res.status_code == 200
    assert db_session.query(Notification).filter(Notification.kind == "event_rescheduled").count() == 3


def test_reschedule_after_reminder_already_sent(client, db_session):
    # Reschedule after a reminder was already sent:
    # a new reminder for the new date is created and sent once when the new date enters the 24h window
    # (the old one is not re-sent); pending reminders for the old date become 'skipped'
    base_now = datetime.now(timezone.utc) + timedelta(days=20)
    old_start = (base_now + timedelta(hours=12)).replace(microsecond=0)

    r = client.post(
        "/api/events",
        json={"title": "Old Date Event", "starts_at": old_start.isoformat(), "capacity": 2},
    )
    assert r.status_code == 201
    event = r.json()
    secret = event["organizer_secret"]
    eid = event["id"]

    client.post(f"/api/events/{eid}/registrations", json={"email": "sent_user@test.com"})
    client.post(f"/api/events/{eid}/registrations", json={"email": "pending_user@test.com"})

    # Run tick at base_now -> both get reminder_24h pending
    run_tick(db_session, base_now)
    notifs = db_session.query(Notification).filter(Notification.kind == "reminder_24h").all()
    assert len(notifs) == 2

    # Manually mark sent_user's reminder as 'sent'
    sent_user = db_session.query(Registration).filter(Registration.email == "sent_user@test.com").one()
    sent_notif = db_session.query(Notification).filter(
        Notification.registration_id == sent_user.id,
        Notification.kind == "reminder_24h"
    ).one()
    sent_notif.status = "sent"
    sent_notif.sent_at = base_now
    db_session.commit()

    # Now reschedule the event to 5 days ahead
    new_start = (base_now + timedelta(days=5)).replace(microsecond=0)
    patch_res = client.patch(f"/api/organizer/{secret}", json={"starts_at": new_start.isoformat()})
    assert patch_res.status_code == 200

    # The pending reminder for pending_user becomes 'skipped'
    pending_user = db_session.query(Registration).filter(Registration.email == "pending_user@test.com").one()
    old_pending_notif = db_session.query(Notification).filter(
        Notification.registration_id == pending_user.id,
        Notification.kind == "reminder_24h",
        Notification.dedup_key == old_start.isoformat(),
    ).one()
    db_session.refresh(old_pending_notif)
    assert old_pending_notif.status == "skipped"

    # Sent reminder stays 'sent'
    db_session.refresh(sent_notif)
    assert sent_notif.status == "sent"

    # Tick at base_now does not create reminder for new date yet (new date is 5 days away)
    run_tick(db_session, base_now)
    new_reminders = db_session.query(Notification).filter(
        Notification.kind == "reminder_24h",
        Notification.dedup_key == new_start.isoformat()
    ).all()
    assert len(new_reminders) == 0

    # Fast-forward time to when new date enters 24h window
    t_new_window = new_start - timedelta(hours=20)
    run_tick(db_session, t_new_window)

    new_reminders = db_session.query(Notification).filter(
        Notification.kind == "reminder_24h",
        Notification.dedup_key == new_start.isoformat()
    ).all()
    # Both confirmed users get a reminder for the new date
    assert len(new_reminders) == 2


def test_cancelled_registration_after_reminder_created_is_skipped_by_worker(client, db_session, smtp_server):
    # A registration cancelled after its reminder was created but before sending ->
    # the worker marks it 'skipped', no email.
    base_now = datetime.now(timezone.utc) + timedelta(days=20)
    event_start = (base_now + timedelta(hours=5)).replace(microsecond=0)

    r = client.post(
        "/api/events",
        json={"title": "Cancel Before Send", "starts_at": event_start.isoformat(), "capacity": 1},
    )
    assert r.status_code == 201
    eid = r.json()["id"]

    reg_res = client.post(f"/api/events/{eid}/registrations", json={"email": "late_cancel@test.com"}).json()
    ticket_code = reg_res["ticket_code"]

    # First empty outbox of the initial ticket notification so our count is clean
    process_outbox_batch(
        db=db_session,
        smtp_host=smtp_server["host"],
        smtp_port=smtp_server["port"],
    )
    smtp_server["handler"].messages.clear()

    # Run scheduler tick -> reminder_24h created
    run_tick(db_session, base_now)
    rem_notif = db_session.query(Notification).filter(Notification.kind == "reminder_24h").one()
    assert rem_notif.status == "pending"

    # Cancel the ticket BEFORE outbox worker runs
    del_res = client.delete(f"/api/tickets/{ticket_code}")
    assert del_res.status_code == 200

    # Run outbox worker
    processed = process_outbox_batch(
        db=db_session,
        smtp_host=smtp_server["host"],
        smtp_port=smtp_server["port"],
    )
    assert processed == 1

    # In database, notification is marked skipped
    db_session.refresh(rem_notif)
    assert rem_notif.status == "skipped"

    # No emails sent for reminder
    assert len(smtp_server["handler"].messages) == 0


def test_end_to_end_reschedule_and_reminder_smtp(client, db_session, smtp_server):
    # End to end with the real in-process SMTP fixture:
    # register 2 people, reschedule, run the outbox worker,
    # exactly 2 'event_rescheduled' emails captured;
    # then tick + worker -> exactly 1 reminder each when the event is within 24h.
    now = datetime.now(timezone.utc)
    original_start = (now + timedelta(days=4)).replace(microsecond=0)

    r = client.post(
        "/api/events",
        json={"title": "Conference 2026", "starts_at": original_start.isoformat(), "capacity": 2},
    )
    assert r.status_code == 201
    event = r.json()
    secret = event["organizer_secret"]
    eid = event["id"]

    client.post(f"/api/events/{eid}/registrations", json={"email": "p1@test.com"})
    client.post(f"/api/events/{eid}/registrations", json={"email": "p2@test.com"})

    # Process and clear ticket emails
    process_outbox_batch(
        db=db_session,
        smtp_host=smtp_server["host"],
        smtp_port=smtp_server["port"],
    )
    smtp_server["handler"].messages.clear()

    # Reschedule event to new future time
    new_start = (now + timedelta(days=2)).replace(microsecond=0)
    reschedule_res = client.patch(f"/api/organizer/{secret}", json={"starts_at": new_start.isoformat()})
    assert reschedule_res.status_code == 200

    # Run outbox worker -> captures exactly 2 'event_rescheduled' emails
    processed_resched = process_outbox_batch(
        db=db_session,
        smtp_host=smtp_server["host"],
        smtp_port=smtp_server["port"],
    )
    assert processed_resched == 2

    resched_msgs = smtp_server["handler"].messages
    assert len(resched_msgs) == 2
    assert {m["rcpt_tos"][0] for m in resched_msgs} == {"p1@test.com", "p2@test.com"}
    for m in resched_msgs:
        assert "Перенос мероприятия" in m["subject"]
        assert "Conference 2026" in m["subject"]
        assert "Старое время" in m["body"]
        assert "Новое время" in m["body"]
        assert "Asia/Almaty" in m["body"]
        assert "UTC" in m["body"]

    smtp_server["handler"].messages.clear()

    # Now move time to within 24h of new_start
    tick_time = new_start - timedelta(hours=10)
    created_reminders = run_tick(db_session, tick_time)
    assert created_reminders == 2

    # Run outbox worker -> captures exactly 1 reminder each (total 2)
    processed_rem = process_outbox_batch(
        db=db_session,
        smtp_host=smtp_server["host"],
        smtp_port=smtp_server["port"],
    )
    assert processed_rem == 2

    rem_msgs = smtp_server["handler"].messages
    assert len(rem_msgs) == 2
    assert {m["rcpt_tos"][0] for m in rem_msgs} == {"p1@test.com", "p2@test.com"}
    for m in rem_msgs:
        assert "Напоминание о мероприятии" in m["subject"]
        assert "Conference 2026" in m["subject"]
        assert "через 24 часа" in m["subject"]
        assert "Статус вашей регистрации: Подтверждено" in m["body"]
        assert "Asia/Almaty" in m["body"]
        assert "UTC" in m["body"]
