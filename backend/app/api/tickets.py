from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.schemas import TicketCancelResponse, TicketResponse
from backend.app.services.registration import cancel_registration, get_ticket_details

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@router.get("/{code}", response_model=TicketResponse)
def get_ticket(code: str, db: Session = Depends(get_db)):
    return get_ticket_details(db, code)


@router.delete("/{code}", response_model=TicketCancelResponse)
def cancel_ticket(code: str, db: Session = Depends(get_db)):
    return cancel_registration(db, code)
