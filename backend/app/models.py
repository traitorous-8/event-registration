from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from backend.app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    capacity = Column(Integer, nullable=False)
    organizer_secret = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    registrations = relationship("Registration", back_populates="event", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("capacity > 0", name="check_event_capacity_positive"),
    )


class Registration(Base):
    __tablename__ = "registrations"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    ticket_code = Column(String(255), nullable=False, unique=True, index=True)
    status = Column(String(50), nullable=False)  # confirmed, waitlist, cancelled
    queued_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    checked_in_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    event = relationship("Event", back_populates="registrations")
    notifications = relationship("Notification", back_populates="registration", cascade="all, delete-orphan")

    __table_args__ = (
        Index("uq_registrations_event_id_email", "event_id", "email", unique=True),
        Index("ix_registrations_queue", "event_id", "status", "queued_at", "id"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    registration_id = Column(Integer, ForeignKey("registrations.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(100), nullable=False)
    dedup_key = Column(String(255), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    status = Column(String(50), nullable=False, default="pending")  # pending, sent, failed
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    registration = relationship("Registration", back_populates="notifications")

    __table_args__ = (
        Index("uq_notifications_registration_kind_dedup", "registration_id", "kind", "dedup_key", unique=True),
    )
