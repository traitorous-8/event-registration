import secrets
from datetime import datetime, timezone
from typing import Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from backend.app.models import Event, Notification, Registration


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register_user(db: Session, event_id: int, raw_email: str) -> Registration:
    normalized_email = normalize_email(raw_email)

    # Begin single atomic transaction with SELECT ... FOR UPDATE on event
    # Using with_for_update() on event
    event = (
        db.query(Event)
        .filter(Event.id == event_id)
        .with_for_update()
        .first()
    )

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )

    now = datetime.now(timezone.utc)
    if event.starts_at <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event has already started"
        )

    # Check if a registration for this event and email already exists
    existing = (
        db.query(Registration)
        .filter(Registration.event_id == event_id, Registration.email == normalized_email)
        .first()
    )

    if existing:
        if existing.status in ("confirmed", "waitlist"):
            # Same email active -> return existing registration
            return existing
        elif existing.status == "cancelled":
            # Reactivate cancelled registration
            # Count current confirmed registrations
            confirmed_count = (
                db.query(func.count(Registration.id))
                .filter(Registration.event_id == event_id, Registration.status == "confirmed")
                .scalar() or 0
            )

            new_status = "confirmed" if confirmed_count < event.capacity else "waitlist"
            existing.status = new_status
            existing.queued_at = now

            # Insert outbox notification on conflict do nothing
            _create_ticket_notification(db, existing.id, existing.ticket_code)

            db.commit()
            db.refresh(existing)
            return existing

    # Create new registration
    confirmed_count = (
        db.query(func.count(Registration.id))
        .filter(Registration.event_id == event_id, Registration.status == "confirmed")
        .scalar() or 0
    )

    new_status = "confirmed" if confirmed_count < event.capacity else "waitlist"
    ticket_code = secrets.token_urlsafe(9)

    registration = Registration(
        event_id=event_id,
        email=normalized_email,
        ticket_code=ticket_code,
        status=new_status,
        queued_at=now,
        created_at=now,
    )
    db.add(registration)
    db.flush()  # populate registration.id

    _create_ticket_notification(db, registration.id, ticket_code)

    db.commit()
    db.refresh(registration)
    return registration


def _create_ticket_notification(db: Session, registration_id: int, ticket_code: str) -> None:
    stmt = insert(Notification).values(
        registration_id=registration_id,
        kind="ticket",
        dedup_key="ticket",
        payload={"ticket_code": ticket_code},
        status="pending",
        attempts=0,
    ).on_conflict_do_nothing(
        index_elements=["registration_id", "kind", "dedup_key"]
    )
    db.execute(stmt)


def get_ticket_details(db: Session, code: str) -> dict:
    registration = (
        db.query(Registration)
        .filter(Registration.ticket_code == code)
        .first()
    )

    if not registration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found"
        )

    event = registration.event
    confirmed_count, waitlist_count, _ = get_event_counts(db, event.id)

    position_in_waitlist = None
    if registration.status == "waitlist":
        # Calculate position in waitlist (1-based) based on queued_at, id
        ahead_count = (
            db.query(func.count(Registration.id))
            .filter(
                Registration.event_id == event.id,
                Registration.status == "waitlist",
                (
                    (Registration.queued_at < registration.queued_at) |
                    ((Registration.queued_at == registration.queued_at) & (Registration.id <= registration.id))
                )
            )
            .scalar() or 0
        )
        position_in_waitlist = ahead_count

    event_data = {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "starts_at": event.starts_at,
        "capacity": event.capacity,
        "created_at": event.created_at,
        "confirmed_count": confirmed_count,
        "waitlist_count": waitlist_count,
    }

    return {
        "status": registration.status,
        "ticket_code": registration.ticket_code,
        "position_in_waitlist": position_in_waitlist,
        "event": event_data,
    }


def cancel_registration(db: Session, code: str) -> dict:
    # Read registration's event_id first
    registration = (
        db.query(Registration)
        .filter(Registration.ticket_code == code)
        .first()
    )

    if not registration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    event_id = registration.event_id

    # Lock order rule: always lock the event row first.
    event = (
        db.query(Event)
        .filter(Event.id == event_id)
        .with_for_update()
        .first()
    )

    now = datetime.now(timezone.utc)
    if event.starts_at <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event has already started",
        )

    # Re-read registration under lock (it may have changed while waiting for the lock)
    # Expire previous registration object so SQLAlchemy loads the latest row state from PostgreSQL
    db.expire(registration)
    registration = (
        db.query(Registration)
        .filter(Registration.ticket_code == code)
        .first()
    )

    if registration.status == "cancelled":
        # status cancelled -> 200 no-op, no second promotion
        return {"status": "cancelled"}

    if registration.status == "waitlist":
        # status waitlist -> set cancelled, no promotion
        registration.status = "cancelled"
        db.commit()
        return {"status": "cancelled"}

    if registration.status == "confirmed":
        # DELETE /api/tickets/{code} on a confirmed registration that is already checked in returns 409
        # (a person who attended cannot cancel); the seat is not released and nobody is promoted.
        if registration.checked_in_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot cancel a registration that has already checked in",
            )

        # status confirmed -> set cancelled, then in SAME transaction promote first waitlist registration
        registration.status = "cancelled"

        earliest_waitlisted = (
            db.query(Registration)
            .filter(Registration.event_id == event_id, Registration.status == "waitlist")
            .order_by(Registration.queued_at.asc(), Registration.id.asc())
            .first()
        )

        if earliest_waitlisted:
            earliest_waitlisted.status = "confirmed"
            _create_waitlist_promoted_notification(
                db,
                earliest_waitlisted.id,
                earliest_waitlisted.ticket_code,
                event.title,
            )

        db.commit()
        return {"status": "cancelled"}

    return {"status": "cancelled"}


def _create_waitlist_promoted_notification(
    db: Session, registration_id: int, ticket_code: str, event_title: str
) -> None:
    stmt = insert(Notification).values(
        registration_id=registration_id,
        kind="waitlist_promoted",
        dedup_key="promoted",
        payload={
            "ticket_code": ticket_code,
            "event_title": event_title,
        },
        status="pending",
        attempts=0,
    ).on_conflict_do_nothing(
        index_elements=["registration_id", "kind", "dedup_key"]
    )
    db.execute(stmt)


def get_event_counts(db: Session, event_id: int) -> Tuple[int, int, int]:
    confirmed_count = (
        db.query(func.count(Registration.id))
        .filter(Registration.event_id == event_id, Registration.status == "confirmed")
        .scalar() or 0
    )
    waitlist_count = (
        db.query(func.count(Registration.id))
        .filter(Registration.event_id == event_id, Registration.status == "waitlist")
        .scalar() or 0
    )
    checked_in_count = (
        db.query(func.count(Registration.id))
        .filter(
            Registration.event_id == event_id,
            Registration.status == "confirmed",
            Registration.checked_in_at.isnot(None),
        )
        .scalar() or 0
    )
    return confirmed_count, waitlist_count, checked_in_count
