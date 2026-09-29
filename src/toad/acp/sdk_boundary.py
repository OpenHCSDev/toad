"""Decode the specification once; typed SDK models own ACP values thereafter."""
from typing import Any
from acp.schema import SessionNotification
from toad.acp.notification_items import NotificationItems


def decode_session_update(session_id: str, update: object,
                          metadata: dict[str, Any] | None = None) -> SessionNotification:
    notification = SessionNotification.model_validate(
        {"sessionId": session_id, "update": update, "_meta": metadata}, strict=True)
    NotificationItems(update).dispatch_sync(notification.update)
    return notification
