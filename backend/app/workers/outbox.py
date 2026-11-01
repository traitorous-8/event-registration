import email.message
import logging
import smtplib
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db import SessionLocal
from backend.app.models import Event, Notification, Registration
from backend.app.workers.templates import build_email_content

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
)
logger = logging.getLogger("outbox_worker")


def send_email(
    smtp_host: str,
    smtp_port: int,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    msg = email.message.EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.send_message(msg)


def process_notification(
    db: Session,
    notification_id: int,
    smtp_host: str,
    smtp_port: int,
    smtp_from: str,
) -> None:
    """
    Process a single notification locked with FOR UPDATE.
    Commit is executed per notification.
    """
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id)
        .with_for_update()
        .first()
    )

    if not notif or notif.status != "pending":
        return

    # Check recipient registration
    registration = (
        db.query(Registration)
        .filter(Registration.id == notif.registration_id)
        .first()
    )

    if not registration:
        logger.error("Notification %d references non-existing registration %d", notif.id, notif.registration_id)
        notif.status = "failed"
        notif.attempts += 1
        db.commit()
        return

    # Before sending a 'reminder_24h' or 'event_rescheduled' notification re-check the registration;
    # if it is 'cancelled' mark the notification 'skipped' and do not send.
    if notif.kind in ("reminder_24h", "event_rescheduled") and registration.status == "cancelled":
        logger.info(
            "Notification %d (%s) skipped because registration %d is cancelled",
            notif.id,
            notif.kind,
            registration.id,
        )
        notif.status = "skipped"
        db.commit()
        return

    event = (
        db.query(Event)
        .filter(Event.id == registration.event_id)
        .first()
    )

    if not event:
        logger.error("Registration %d references non-existing event %d", registration.id, registration.event_id)
        notif.status = "failed"
        notif.attempts += 1
        db.commit()
        return

    recipient = registration.email

    try:
        subject, body = build_email_content(
            kind=notif.kind,
            payload=notif.payload or {},
            registration_status=registration.status,
            event_title=event.title,
            event_starts_at=event.starts_at,
        )
    except ValueError as e:
        logger.warning("Notification %d has unknown kind '%s': %s", notif.id, notif.kind, e)
        notif.status = "failed"
        notif.attempts += 1
        db.commit()
        return

    try:
        send_email(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            sender=smtp_from,
            recipient=recipient,
            subject=subject,
            body=body,
        )
        notif.status = "sent"
        notif.sent_at = datetime.now(timezone.utc)
        logger.info("Delivered notification %d (%s) to %s", notif.id, notif.kind, recipient)
    except Exception as exc:
        notif.attempts += 1
        if notif.attempts >= 5:
            notif.status = "failed"
            logger.error(
                "Notification %d delivery failed permanently (%d attempts): %s",
                notif.id,
                notif.attempts,
                exc,
            )
        else:
            logger.warning(
                "Notification %d delivery failed temporarily (attempt %d): %s",
                notif.id,
                notif.attempts,
                exc,
            )

    db.commit()


def process_outbox_batch(
    db: Session,
    batch_size: int = settings.outbox_batch_size,
    smtp_host: str = settings.smtp_host,
    smtp_port: int = settings.smtp_port,
    smtp_from: str = settings.smtp_from,
) -> int:
    """
    Selects up to batch_size pending notification IDs using FOR UPDATE SKIP LOCKED
    and processes each row with per-message commits.
    Returns the number of processed notifications.
    """
    # Select candidate IDs with SKIP LOCKED
    candidate_ids = (
        db.query(Notification.id)
        .filter(Notification.status == "pending")
        .order_by(Notification.id.asc())
        .with_for_update(skip_locked=True)
        .limit(batch_size)
        .all()
    )

    ids = [cid[0] for cid in candidate_ids]
    if not ids:
        return 0

    # For each selected notification, process in individual commit
    for nid in ids:
        try:
            process_notification(
                db=db,
                notification_id=nid,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_from=smtp_from,
            )
        except Exception as e:
            logger.exception("Unexpected error processing notification %d: %s", nid, e)
            db.rollback()

    return len(ids)


def run_worker_loop(stop_event=None) -> None:
    logger.info(
        "Starting Outbox Worker (poll=%ss, batch=%d, smtp=%s:%d, from=%s)",
        settings.outbox_poll_seconds,
        settings.outbox_batch_size,
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_from,
    )

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Outbox Worker received stop signal.")
            break

        db = SessionLocal()
        try:
            processed = process_outbox_batch(db)
        except Exception as e:
            logger.exception("Error during outbox batch processing: %s", e)
            db.rollback()
            processed = 0
        finally:
            db.close()

        # If stop_event is given and set, exit immediately
        if stop_event and stop_event.is_set():
            break

        # Poll sleep
        time.sleep(settings.outbox_poll_seconds)


if __name__ == "__main__":
    try:
        run_worker_loop()
    except KeyboardInterrupt:
        logger.info("Worker stopped by KeyboardInterrupt.")
        sys.exit(0)
