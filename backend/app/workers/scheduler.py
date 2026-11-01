import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db import SessionLocal
from backend.app.models import Event, Notification, Registration

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
)
logger = logging.getLogger("scheduler")


def run_tick(session: Session, now: datetime) -> int:
    """
    Executes one tick of the reminder scheduler.
    Finds events with:
      starts_at > now and starts_at - now <= 24h
    For every registration with status 'confirmed', inserts one notification:
      kind='reminder_24h'
      dedup_key=<event starts_at as ISO UTC string>
      payload with event data
      INSERT ... ON CONFLICT DO NOTHING
    Returns total reminder notifications attempted / inserted.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    window_end = now + timedelta(hours=24)

    # Find events within (now, now + 24 hours]
    events = (
        session.query(Event)
        .filter(and_(Event.starts_at > now, Event.starts_at <= window_end))
        .all()
    )

    created_count = 0

    for event in events:
        starts_at_utc = (
            event.starts_at.astimezone(timezone.utc)
            if event.starts_at.tzinfo
            else event.starts_at.replace(tzinfo=timezone.utc)
        )
        dedup_key = starts_at_utc.isoformat()

        # Query all confirmed registrations for this event
        confirmed_registrations = (
            session.query(Registration)
            .filter(
                Registration.event_id == event.id,
                Registration.status == "confirmed",
            )
            .all()
        )

        for reg in confirmed_registrations:
            payload = {
                "event_id": event.id,
                "event_title": event.title,
                "ticket_code": reg.ticket_code,
                "starts_at": starts_at_utc.isoformat(),
            }

            stmt = insert(Notification).values(
                registration_id=reg.id,
                kind="reminder_24h",
                dedup_key=dedup_key,
                payload=payload,
                status="pending",
                attempts=0,
            ).on_conflict_do_nothing(
                index_elements=["registration_id", "kind", "dedup_key"]
            )
            res = session.execute(stmt)
            if res.rowcount and res.rowcount > 0:
                created_count += res.rowcount

    session.commit()
    return created_count


def run_scheduler_loop(stop_event=None) -> None:
    logger.info(
        "Starting Scheduler Worker (poll=%ss)",
        settings.scheduler_poll_seconds,
    )

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Scheduler Worker received stop signal.")
            break

        session = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            created = run_tick(session, now)
            if created > 0:
                logger.info("Scheduler tick created %d reminders", created)
        except Exception as e:
            logger.exception("Error during scheduler tick: %s", e)
            session.rollback()
        finally:
            session.close()

        if stop_event and stop_event.is_set():
            break

        time.sleep(settings.scheduler_poll_seconds)


if __name__ == "__main__":
    try:
        run_scheduler_loop()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by KeyboardInterrupt.")
        sys.exit(0)
