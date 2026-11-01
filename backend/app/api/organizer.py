import secrets
from datetime import timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Event, Notification, Registration
from backend.app.schemas import (
    CheckInRequest,
    CheckInResponse,
    EventReschedule,
    EventResponse,
    OrganizerEventResponse,
    ParticipantItem,
)
from backend.app.services.registration import get_event_counts

router = APIRouter(prefix="/api/organizer", tags=["organizer"])


def _find_event_by_secret(db: Session, secret: str) -> Event:
    events = db.query(Event).all()
    for ev in events:
        if secrets.compare_digest(ev.organizer_secret, secret):
            return ev
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Event not found",
    )


@router.post("/{secret}/checkin", response_model=CheckInResponse)
def checkin_participant(
    secret: str,
    payload: CheckInRequest,
    db: Session = Depends(get_db),
):
    event = _find_event_by_secret(db, secret)

    # One atomic statement:
    # UPDATE registrations SET checked_in_at=now()
    # WHERE ticket_code=:c AND event_id=:event AND status='confirmed' AND checked_in_at IS NULL
    # RETURNING ... Never SELECT-then-UPDATE.
    stmt = text(
        """
        UPDATE registrations
        SET checked_in_at = now()
        WHERE ticket_code = :ticket_code
          AND event_id = :event_id
          AND status = 'confirmed'
          AND checked_in_at IS NULL
        RETURNING id, email, ticket_code, checked_in_at
        """
    )
    result = db.execute(
        stmt,
        {"ticket_code": payload.ticket_code, "event_id": event.id},
    ).mappings().first()

    if result:
        db.commit()
        return CheckInResponse(
            email=result["email"],
            ticket_code=result["ticket_code"],
            checked_in_at=result["checked_in_at"],
        )

    # If no row was updated, find out why with a follow-up read:
    # 404 if the code does not exist or belongs to another event,
    # 409 if already checked in (include checked_in_at),
    # 422 if the registration is not 'confirmed' (waitlist or cancelled).
    reg = db.query(Registration).filter(
        Registration.ticket_code == payload.ticket_code,
        Registration.event_id == event.id,
    ).first()

    if not reg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found for this event",
        )

    if reg.checked_in_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Participant is already checked in",
                "checked_in_at": reg.checked_in_at.isoformat(),
            },
        )

    if reg.status != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Registration status is '{reg.status}', only confirmed tickets can check in",
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unable to check in",
    )


@router.get("/{secret}", response_model=OrganizerEventResponse)
def get_organizer_event(
    secret: str,
    db: Session = Depends(get_db),
):
    event = _find_event_by_secret(db, secret)

    confirmed_count, waitlist_count, checked_in_count = get_event_counts(db, event.id)

    registrations = (
        db.query(Registration)
        .filter(Registration.event_id == event.id)
        .order_by(Registration.queued_at.asc(), Registration.id.asc())
        .all()
    )

    participants = [
        ParticipantItem(
            email=reg.email,
            status=reg.status,
            ticket_code=reg.ticket_code,
            queued_at=reg.queued_at,
            checked_in_at=reg.checked_in_at,
        )
        for reg in registrations
    ]

    return OrganizerEventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        starts_at=event.starts_at,
        capacity=event.capacity,
        created_at=event.created_at,
        confirmed_count=confirmed_count,
        waitlist_count=waitlist_count,
        checked_in_count=checked_in_count,
        participants=participants,
    )


@router.patch("/{secret}", response_model=EventResponse)
def reschedule_event(
    secret: str,
    payload: EventReschedule,
    db: Session = Depends(get_db),
):
    # Find event by organizer_secret using secrets.compare_digest.
    # Wrong secret -> 404 (do not reveal that the event exists).
    events = db.query(Event).all()
    matched_event = None
    for ev in events:
        if secrets.compare_digest(ev.organizer_secret, secret):
            matched_event = ev
            break

    if not matched_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    # In one transaction: lock the event row FOR UPDATE
    event = (
        db.query(Event)
        .filter(Event.id == matched_event.id)
        .with_for_update()
        .first()
    )

    current_starts_at_utc = (
        event.starts_at.astimezone(timezone.utc)
        if event.starts_at.tzinfo
        else event.starts_at.replace(tzinfo=timezone.utc)
    )
    new_starts_at_utc = (
        payload.starts_at.astimezone(timezone.utc)
        if payload.starts_at.tzinfo
        else payload.starts_at.replace(tzinfo=timezone.utc)
    )

    # Same value as current -> 200, no changes, no notifications.
    if current_starts_at_utc == new_starts_at_utc:
        confirmed_count, waitlist_count, _ = get_event_counts(db, event.id)
        return EventResponse(
            id=event.id,
            title=event.title,
            description=event.description,
            starts_at=event.starts_at,
            capacity=event.capacity,
            created_at=event.created_at,
            confirmed_count=confirmed_count,
            waitlist_count=waitlist_count,
        )

    # Update starts_at
    old_starts_at_iso = current_starts_at_utc.isoformat()
    new_starts_at_iso = new_starts_at_utc.isoformat()

    event.starts_at = new_starts_at_utc

    # Mark pending 'reminder_24h' notifications of this event whose dedup_key differs
    # from the new date as 'skipped'
    # Find registration IDs for this event
    reg_ids = [
        r[0]
        for r in db.query(Registration.id)
        .filter(Registration.event_id == event.id)
        .all()
    ]

    if reg_ids:
        db.execute(
            update(Notification)
            .where(
                and_(
                    Notification.registration_id.in_(reg_ids),
                    Notification.kind == "reminder_24h",
                    Notification.status == "pending",
                    Notification.dedup_key != new_starts_at_iso,
                )
            )
            .values(status="skipped")
        )

        # Insert one notification (kind='event_rescheduled', dedup_key=<new starts_at ISO>,
        # payload with old and new times) for every 'confirmed' and 'waitlist' registration,
        # ON CONFLICT DO NOTHING.
        active_regs = (
            db.query(Registration)
            .filter(
                Registration.event_id == event.id,
                Registration.status.in_(["confirmed", "waitlist"]),
            )
            .all()
        )

        for reg in active_regs:
            reschedule_payload = {
                "event_id": event.id,
                "event_title": event.title,
                "ticket_code": reg.ticket_code,
                "old_starts_at": old_starts_at_iso,
                "new_starts_at": new_starts_at_iso,
            }

            stmt = insert(Notification).values(
                registration_id=reg.id,
                kind="event_rescheduled",
                dedup_key=new_starts_at_iso,
                payload=reschedule_payload,
                status="pending",
                attempts=0,
            ).on_conflict_do_nothing(
                index_elements=["registration_id", "kind", "dedup_key"]
            )
            db.execute(stmt)

    db.commit()
    db.refresh(event)

    confirmed_count, waitlist_count, _ = get_event_counts(db, event.id)
    return EventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        starts_at=event.starts_at,
        capacity=event.capacity,
        created_at=event.created_at,
        confirmed_count=confirmed_count,
        waitlist_count=waitlist_count,
    )
