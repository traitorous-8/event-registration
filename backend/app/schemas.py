from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    starts_at: datetime
    capacity: int

    @field_validator("starts_at")
    @classmethod
    def validate_starts_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("starts_at must be timezone-aware")
        if v <= datetime.now(timezone.utc):
            raise ValueError("starts_at must be in the future")
        return v

    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("capacity must be greater than 0")
        return v


class EventResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    starts_at: datetime
    capacity: int
    created_at: datetime
    confirmed_count: int
    waitlist_count: int

    model_config = ConfigDict(from_attributes=True)


class EventCreateResponse(EventResponse):
    organizer_secret: str


class EventReschedule(BaseModel):
    starts_at: datetime

    @field_validator("starts_at")
    @classmethod
    def validate_starts_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("starts_at must be timezone-aware")
        if v <= datetime.now(timezone.utc):
            raise ValueError("starts_at must be in the future")
        return v


class RegistrationCreate(BaseModel):
    email: EmailStr


class RegistrationResponse(BaseModel):
    status: str
    ticket_code: str

    model_config = ConfigDict(from_attributes=True)


class TicketResponse(BaseModel):
    status: str
    ticket_code: str
    position_in_waitlist: Optional[int] = None
    event: EventResponse


class TicketCancelResponse(BaseModel):
    status: str = "cancelled"


class CheckInRequest(BaseModel):
    ticket_code: str


class CheckInResponse(BaseModel):
    email: EmailStr
    ticket_code: str
    checked_in_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizerCounters(BaseModel):
    confirmed: int
    waitlist: int
    checked_in: int


class OrganizerParticipant(BaseModel):
    email: str
    status: str
    ticket_code: str
    queued_at: datetime
    checked_in_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OrganizerViewResponse(BaseModel):
    event: EventResponse
    counters: OrganizerCounters
    participants: list[OrganizerParticipant]
