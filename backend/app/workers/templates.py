from datetime import datetime
from typing import Tuple
from zoneinfo import ZoneInfo

ALMATY_TZ = ZoneInfo("Asia/Almaty")


def format_event_datetime(dt: datetime) -> str:
    """Format datetime in UTC and Asia/Almaty."""
    # Ensure dt is aware
    utc_str = dt.strftime("%Y-%m-%d %H:%M UTC")
    almaty_dt = dt.astimezone(ALMATY_TZ)
    almaty_str = almaty_dt.strftime("%Y-%m-%d %H:%M Asia/Almaty")
    return f"{utc_str} / {almaty_str}"


def build_email_content(
    kind: str,
    payload: dict,
    registration_status: str,
    event_title: str,
    event_starts_at: datetime,
) -> Tuple[str, str]:
    """
    Returns (subject, body) in Russian plain text.
    Raises ValueError if kind is unknown.
    """
    time_str = format_event_datetime(event_starts_at)
    ticket_code = payload.get("ticket_code", "")

    if kind == "ticket":
        subject = f"Ваш билет на мероприятие «{event_title}»"
        status_label = "Подтверждено (место забронировано)" if registration_status == "confirmed" else "Лист ожидания"
        body = (
            f"Здравствуйте!\n\n"
            f"Вы зарегистрированы на мероприятие: «{event_title}»\n"
            f"Время начала: {time_str}\n"
            f"Текущий статус регистрации: {status_label}\n"
            f"Код вашего билета: {ticket_code}\n\n"
            f"Если вы не сможете прийти, вы можете отказаться от участия в любое время:\n"
            f"DELETE /api/tickets/{ticket_code}\n"
        )
        return subject, body

    elif kind == "waitlist_promoted":
        subject = f"Вам предоставлено место на мероприятие «{event_title}»"
        body = (
            f"Здравствуйте!\n\n"
            f"Отличная новость! Вы получили подтверждённое место на мероприятие «{event_title}» из листа ожидания.\n"
            f"Время начала: {time_str}\n"
            f"Код вашего билета: {ticket_code}\n\n"
            f"Если вы не сможете прийти, пожалуйста, отмените регистрацию:\n"
            f"DELETE /api/tickets/{ticket_code}\n"
        )
        return subject, body

    elif kind == "reminder_24h":
        subject = f"Напоминание о мероприятии «{event_title}» через 24 часа"
        status_label = "Подтверждено (место забронировано)" if registration_status == "confirmed" else registration_status
        body = (
            f"Здравствуйте!\n\n"
            f"Напоминаем, что через 24 часа состоится мероприятие: «{event_title}»\n"
            f"Время начала: {time_str}\n"
            f"Код вашего билета: {ticket_code}\n"
            f"Статус вашей регистрации: {status_label}\n\n"
            f"Если ваши планы изменились, пожалуйста, освободите место:\n"
            f"DELETE /api/tickets/{ticket_code}\n"
        )
        return subject, body

    elif kind == "event_rescheduled":
        subject = f"Перенос мероприятия «{event_title}»"
        old_time_iso = payload.get("old_starts_at")
        new_time_iso = payload.get("new_starts_at")

        old_dt = datetime.fromisoformat(old_time_iso) if old_time_iso else event_starts_at
        new_dt = datetime.fromisoformat(new_time_iso) if new_time_iso else event_starts_at

        old_time_str = format_event_datetime(old_dt)
        new_time_str = format_event_datetime(new_dt)

        body = (
            f"Здравствуйте!\n\n"
            f"Обратите внимание: мероприятие «{event_title}» перенесено на новое время.\n"
            f"Старое время: {old_time_str}\n"
            f"Новое время: {new_time_str}\n"
            f"Код вашего билета: {ticket_code}\n\n"
            f"Если вам не подходит новая дата, вы можете отказаться от участия:\n"
            f"DELETE /api/tickets/{ticket_code}\n"
        )
        return subject, body

    else:
        raise ValueError(f"Unknown notification kind: {kind}")
