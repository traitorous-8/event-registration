import asyncio
import json
import secrets
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db import SessionLocal, get_db
from backend.app.models import Event
from backend.app.schemas import (
    EventCreate,
    EventCreateResponse,
    EventResponse,
    RegistrationCreate,
    RegistrationResponse,
)
from backend.app.events_bus import bus
from backend.app.services.registration import (
    get_event_counts,
    register_user,
)

router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("", response_model=EventCreateResponse, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, db: Session = Depends(get_db)):
    organizer_secret = secrets.token_urlsafe(32)
    event = Event(
        title=payload.title,
        description=payload.description,
        starts_at=payload.starts_at,
        capacity=payload.capacity,
        organizer_secret=organizer_secret,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    confirmed_count, waitlist_count = get_event_counts(db, event.id)

    return EventCreateResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        starts_at=event.starts_at,
        capacity=event.capacity,
        organizer_secret=event.organizer_secret,
        created_at=event.created_at,
        confirmed_count=confirmed_count,
        waitlist_count=waitlist_count,
    )


@router.get("", response_model=List[EventResponse])
def list_events(db: Session = Depends(get_db)):
    events = db.query(Event).order_by(Event.id.asc()).all()
    result = []
    for event in events:
        confirmed_count, waitlist_count = get_event_counts(db, event.id)
        result.append(
            EventResponse(
                id=event.id,
                title=event.title,
                description=event.description,
                starts_at=event.starts_at,
                capacity=event.capacity,
                created_at=event.created_at,
                confirmed_count=confirmed_count,
                waitlist_count=waitlist_count,
            )
        )
    return result


@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )

    confirmed_count, waitlist_count = get_event_counts(db, event.id)
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


@router.post("/{event_id}/registrations", response_model=RegistrationResponse)
def register_for_event(
    event_id: int,
    payload: RegistrationCreate,
    db: Session = Depends(get_db),
):
    registration = register_user(db, event_id=event_id, raw_email=payload.email)
    bus.publish(event_id)
    return RegistrationResponse(
        status=registration.status,
        ticket_code=registration.ticket_code,
    )


def _fetch_event_counts(event_id: int) -> dict:
    session = SessionLocal()
    try:
        confirmed, waitlist = get_event_counts(session, event_id)
        return {"confirmed": confirmed, "waitlist": waitlist}
    finally:
        session.close()


@router.get("/{event_id}/stream")
async def event_stream(event_id: int, request: Request, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    loop, queue = bus.subscribe(event_id)

    async def event_generator():
        try:
            # Immediate snapshot on connect
            counts = await run_in_threadpool(_fetch_event_counts, event_id)
            yield f"event: counts\ndata: {json.dumps(counts)}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    await asyncio.wait_for(queue.get(), timeout=settings.sse_heartbeat_seconds)
                    # Snapshot after change
                    counts = await run_in_threadpool(_fetch_event_counts, event_id)
                    yield f"event: counts\ndata: {json.dumps(counts)}\n\n"
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(event_id, loop, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
