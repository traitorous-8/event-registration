from datetime import datetime, timezone
import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.models import Event, Registration, Notification


def test_unique_index_registrations_event_id_email(db_session):
    event = Event(
        title="Tech Conference",
        starts_at=datetime.now(timezone.utc),
        capacity=100,
        organizer_secret="secret_123"
    )
    db_session.add(event)
    db_session.commit()

    reg1 = Registration(
        event_id=event.id,
        email="test@example.com",
        ticket_code="code_1",
        status="confirmed",
        queued_at=datetime.now(timezone.utc)
    )
    db_session.add(reg1)
    db_session.commit()

    # Attempt to insert duplicate registration (same event_id and email)
    reg2 = Registration(
        event_id=event.id,
        email="test@example.com",
        ticket_code="code_2",
        status="confirmed",
        queued_at=datetime.now(timezone.utc)
    )
    db_session.add(reg2)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()

    assert "uq_registrations_event_id_email" in str(exc_info.value) or "unique constraint" in str(exc_info.value).lower()


def test_unique_index_notifications_registration_kind_dedup(db_session):
    event = Event(
        title="Tech Conference",
        starts_at=datetime.now(timezone.utc),
        capacity=100,
        organizer_secret="secret_456"
    )
    db_session.add(event)
    db_session.commit()

    reg = Registration(
        event_id=event.id,
        email="user@example.com",
        ticket_code="code_3",
        status="confirmed",
        queued_at=datetime.now(timezone.utc)
    )
    db_session.add(reg)
    db_session.commit()

    notif1 = Notification(
        registration_id=reg.id,
        kind="registration_confirmed",
        dedup_key="dedup_001",
        payload={"ticket": "code_3"},
        status="pending"
    )
    db_session.add(notif1)
    db_session.commit()

    # Attempt to insert duplicate notification (same registration_id, kind, dedup_key)
    notif2 = Notification(
        registration_id=reg.id,
        kind="registration_confirmed",
        dedup_key="dedup_001",
        payload={"ticket": "code_3"},
        status="pending"
    )
    db_session.add(notif2)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()

    assert "uq_notifications_registration_kind_dedup" in str(exc_info.value) or "unique constraint" in str(exc_info.value).lower()
