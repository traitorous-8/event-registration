import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db import SessionLocal, get_db
from backend.app.events_bus import bus
from backend.app.models import Registration
from backend.app.schemas import TicketCancelResponse, TicketResponse
from backend.app.services.registration import cancel_registration, get_ticket_details

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@router.get("/{code}", response_model=TicketResponse)
def get_ticket(code: str, db: Session = Depends(get_db)):
    return get_ticket_details(db, code)


@router.delete("/{code}", response_model=TicketCancelResponse)
def cancel_ticket(code: str, db: Session = Depends(get_db)):
    # To publish for the correct event_id after successful cancellation:
    # Query event_id first or after cancel_registration returns successfully
    reg = db.query(Registration.event_id).filter(Registration.ticket_code == code).first()
    event_id = reg[0] if reg else None

    result = cancel_registration(db, code)
    if event_id is not None:
        bus.publish(event_id)
    return result


def _fetch_ticket_snapshot(code: str) -> dict:
    session = SessionLocal()
    try:
        details = get_ticket_details(session, code)
        return {
            "status": details["status"],
            "position_in_waitlist": details["position_in_waitlist"],
        }
    finally:
        session.close()


@router.get("/{code}/stream")
async def ticket_stream(code: str, request: Request, db: Session = Depends(get_db)):
    reg = db.query(Registration).filter(Registration.ticket_code == code).first()
    if not reg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )
    event_id = reg.event_id

    loop, queue = bus.subscribe(event_id)

    async def ticket_generator():
        try:
            # Immediate snapshot on connect
            data = await run_in_threadpool(_fetch_ticket_snapshot, code)
            yield f"event: ticket\ndata: {json.dumps(data)}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    await asyncio.wait_for(queue.get(), timeout=settings.sse_heartbeat_seconds)
                    data = await run_in_threadpool(_fetch_ticket_snapshot, code)
                    yield f"event: ticket\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(event_id, loop, queue)

    return StreamingResponse(
        ticket_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
