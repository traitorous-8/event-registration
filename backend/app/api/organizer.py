import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Event, Registration
from backend.app.schemas import (
    CheckInRequest,
    CheckInResponse,
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
    # 409 if already checked in (include checked_in_at in the body),
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
