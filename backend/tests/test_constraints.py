from datetime import datetime, timezone
import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.models import Event, Notification, Registration


def test_check_constraint_rejects_invalid_registration_status(db_session):
    event = Event(
        title="Status Event",
        starts_at=datetime.now(timezone.utc),
        capacity=10,
        organizer_secret="secret_stat",
    )
    db_session.add(event)
    db_session.commit()

    reg = Registration(
        event_id=event.id,
        email="user@test.com",
        ticket_code="code_stat",
        status="invalid_status",
        queued_at=datetime.now(timezone.utc),
    )
    db_session.add(reg)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()

    assert "check_registration_status_valid" in str(exc_info.value) or "check constraint" in str(exc_info.value).lower()


def test_check_constraint_rejects_uppercase_email(db_session):
    event = Event(
        title="Email Event",
        starts_at=datetime.now(timezone.utc),
        capacity=10,
        organizer_secret="secret_email",
    )
    db_session.add(event)
    db_session.commit()

    reg = Registration(
        event_id=event.id,
        email="Uppercase@Test.com",
        ticket_code="code_email",
        status="confirmed",
        queued_at=datetime.now(timezone.utc),
    )
    db_session.add(reg)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()

    assert "check_registration_email_lowercased" in str(exc_info.value) or "check constraint" in str(exc_info.value).lower()


def test_check_constraint_rejects_invalid_notification_status(db_session):
    event = Event(
        title="Notif Event",
        starts_at=datetime.now(timezone.utc),
        capacity=10,
        organizer_secret="secret_notif",
    )
    db_session.add(event)
    db_session.commit()

    reg = Registration(
        event_id=event.id,
        email="user_notif@test.com",
        ticket_code="code_notif",
        status="confirmed",
        queued_at=datetime.now(timezone.utc),
    )
    db_session.add(reg)
    db_session.commit()

    notif = Notification(
        registration_id=reg.id,
        kind="ticket",
        dedup_key="ticket",
        payload={"ticket": "code_notif"},
        status="invalid_status",
    )
    db_session.add(notif)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()

    assert "check_notification_status_valid" in str(exc_info.value) or "check constraint" in str(exc_info.value).lower()
