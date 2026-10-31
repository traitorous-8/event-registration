import concurrent.futures
import threading
from datetime import datetime, timezone
import pytest
from aiosmtpd.controller import Controller

from backend.app.models import Event, Notification, Registration
from backend.app.workers.outbox import process_outbox_batch
from backend.tests.test_stage2_registration import create_event_via_api


import email
import email.policy

class RecordingHandler:
    def __init__(self):
        self.messages = []
        self._lock = threading.Lock()

    async def handle_DATA(self, server, session, envelope):
        raw_content = envelope.content.decode("utf8", errors="replace")
        msg = email.message_from_string(raw_content, policy=email.policy.default)
        with self._lock:
            self.messages.append(
                {
                    "mail_from": envelope.mail_from,
                    "rcpt_tos": envelope.rcpt_tos,
                    "subject": msg["Subject"],
                    "body": msg.get_content() if msg.is_multipart() is False else "",
                    "raw": raw_content,
                }
            )
        return "250 Message accepted for delivery"


import socket

@pytest.fixture
def smtp_server():
    handler = RecordingHandler()
    # Find free port
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free_port = s.getsockname()[1]
    s.close()

    controller = Controller(handler, hostname="127.0.0.1", port=free_port)
    controller.start()

    yield {
        "host": "127.0.0.1",
        "port": free_port,
        "handler": handler,
        "controller": controller,
    }

    controller.stop()


def test_ticket_notification_delivered_once(client, db_session, smtp_server):
    event = create_event_via_api(client, title="PyCon 2026", capacity=5)
    r = client.post(f"/api/events/{event['id']}/registrations", json={"email": "alice@test.com"})
    assert r.status_code == 200

    notif = db_session.query(Notification).filter(Notification.kind == "ticket").one()
    assert notif.status == "pending"
    assert notif.sent_at is None

    # Run worker batch
    processed = process_outbox_batch(
        db=db_session,
        batch_size=10,
        smtp_host=smtp_server["host"],
        smtp_port=smtp_server["port"],
        smtp_from="noreply@events.local",
    )
    assert processed == 1

    # Verify captured email
    msgs = smtp_server["handler"].messages
    assert len(msgs) == 1
    assert msgs[0]["rcpt_tos"] == ["alice@test.com"]
    assert msgs[0]["mail_from"] == "noreply@events.local"
    assert "PyCon 2026" in msgs[0]["subject"]
    assert "PyCon 2026" in msgs[0]["body"]
    assert "DELETE /api/tickets/" in msgs[0]["body"]
    assert "UTC" in msgs[0]["body"]
    assert "Asia/Almaty" in msgs[0]["body"]

    # Verify notification row updated
    db_session.refresh(notif)
    assert notif.status == "sent"
    assert notif.sent_at is not None
    assert notif.attempts == 0


def test_two_workers_in_parallel_deliver_each_exactly_once(client, db_session, test_engine, smtp_server):
    event = create_event_via_api(client, title="Parallel Outbox Event", capacity=10)
    eid = event["id"]

    for i in range(10):
        client.post(f"/api/events/{eid}/registrations", json={"email": f"user_{i}@test.com"})

    pending_count = db_session.query(Notification).filter(Notification.status == "pending").count()
    assert pending_count == 10

    from sqlalchemy.orm import sessionmaker
    SessionLocalTest = sessionmaker(bind=test_engine)

    barrier = threading.Barrier(2)

    def worker_job():
        barrier.wait()
        sess = SessionLocalTest()
        try:
            return process_outbox_batch(
                db=sess,
                batch_size=10,
                smtp_host=smtp_server["host"],
                smtp_port=smtp_server["port"],
                smtp_from="noreply@events.local",
            )
        finally:
            sess.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(worker_job)
        f2 = executor.submit(worker_job)
        p1 = f1.result()
        p2 = f2.result()

    # Total processed across both workers must equal 10
    assert p1 + p2 == 10

    # Exactly 10 emails sent to MailHog/SMTP
    msgs = smtp_server["handler"].messages
    assert len(msgs) == 10
    recipients = {m["rcpt_tos"][0] for m in msgs}
    assert len(recipients) == 10

    # In database, all 10 are sent
    all_notifs = db_session.query(Notification).all()
    assert all(n.status == "sent" for n in all_notifs)


def test_smtp_failure_retries_and_marks_failed_after_5(client, db_session, smtp_server):
    event = create_event_via_api(client, title="Failure Event", capacity=1)
    client.post(f"/api/events/{event['id']}/registrations", json={"email": "fail_test@test.com"})

    notif = db_session.query(Notification).one()
    assert notif.status == "pending"
    assert notif.attempts == 0

    # Point to non-existent SMTP port to simulate failure
    bad_port = smtp_server["port"] + 999

    # Attempts 1 to 4: attempts increment, status stays pending
    for expected_attempts in range(1, 5):
        processed = process_outbox_batch(
            db=db_session,
            batch_size=1,
            smtp_host="127.0.0.1",
            smtp_port=bad_port,
        )
        assert processed == 1
        db_session.refresh(notif)
        assert notif.status == "pending"
        assert notif.attempts == expected_attempts

    # Attempt 5: status becomes failed
    processed = process_outbox_batch(
        db=db_session,
        batch_size=1,
        smtp_host="127.0.0.1",
        smtp_port=bad_port,
    )
    assert processed == 1
    db_session.refresh(notif)
    assert notif.status == "failed"
    assert notif.attempts == 5

    # Check recovery: create a second notification and deliver when SMTP works
    client.post(f"/api/events/{event['id']}/registrations", json={"email": "recovery@test.com"})
    notif2 = db_session.query(Notification).filter(Notification.status == "pending").one()

    # Point back to active smtp_server
    processed = process_outbox_batch(
        db=db_session,
        batch_size=5,
        smtp_host=smtp_server["host"],
        smtp_port=smtp_server["port"],
    )
    assert processed == 1
    db_session.refresh(notif2)
    assert notif2.status == "sent"
    assert notif2.sent_at is not None


def test_end_to_end_cancellation_and_promotion_emails(client, db_session, smtp_server):
    # Register through the API on a capacity-1 event with two emails,
    # cancel the first ticket, run the worker, and check that three messages were captured:
    # ticket for a, ticket for b, waitlist_promoted for b, each exactly once.
    event = create_event_via_api(client, title="Grand Opening", capacity=1)
    eid = event["id"]

    r1 = client.post(f"/api/events/{eid}/registrations", json={"email": "user_a@test.com"}).json()
    r2 = client.post(f"/api/events/{eid}/registrations", json={"email": "user_b@test.com"}).json()

    # Cancel first ticket
    del_res = client.delete(f"/api/tickets/{r1['ticket_code']}")
    assert del_res.status_code == 200

    # Run outbox worker
    processed = process_outbox_batch(
        db=db_session,
        batch_size=10,
        smtp_host=smtp_server["host"],
        smtp_port=smtp_server["port"],
        smtp_from="noreply@events.local",
    )
    assert processed == 3

    msgs = smtp_server["handler"].messages
    assert len(msgs) == 3

    # Check messages
    # 1. ticket for user_a
    # 2. ticket for user_b
    # 3. waitlist_promoted for user_b
    a_msgs = [m for m in msgs if m["rcpt_tos"] == ["user_a@test.com"]]
    b_msgs = [m for m in msgs if m["rcpt_tos"] == ["user_b@test.com"]]

    assert len(a_msgs) == 1
    assert "Ваш билет" in a_msgs[0]["subject"]
    assert "Grand Opening" in a_msgs[0]["body"]

    assert len(b_msgs) == 2
    b_subjects = [m["subject"] for m in b_msgs]
    # One ticket email and one waitlist_promoted email
    assert any("Ваш билет" in s for s in b_subjects)
    assert any("Вам предоставлено место" in s for s in b_subjects)


def test_rerun_worker_with_nothing_pending_sends_nothing(db_session, smtp_server):
    processed = process_outbox_batch(
        db=db_session,
        batch_size=10,
        smtp_host=smtp_server["host"],
        smtp_port=smtp_server["port"],
    )
    assert processed == 0
    assert len(smtp_server["handler"].messages) == 0


def test_unknown_notification_kind_marks_failed_and_keeps_worker_running(client, db_session, smtp_server):
    event = create_event_via_api(client, title="Unknown Kind Event", capacity=5)
    r = client.post(f"/api/events/{event['id']}/registrations", json={"email": "unknown@test.com"}).json()

    notif = db_session.query(Notification).one()
    # Change kind to something unknown
    notif.kind = "unsupported_kind"
    db_session.commit()

    # Run worker batch
    processed = process_outbox_batch(
        db=db_session,
        batch_size=10,
        smtp_host=smtp_server["host"],
        smtp_port=smtp_server["port"],
    )
    assert processed == 1

    db_session.refresh(notif)
    assert notif.status == "failed"
    assert notif.attempts == 1

    # No emails sent
    assert len(smtp_server["handler"].messages) == 0
