"""Validate ACP v1 notifications without rewriting extension-bearing wire data."""

from typing import Any, cast

from toad.acp import protocol


def validate_session_update(
    session_id: str, update: object, metadata: dict[str, Any] | None = None
) -> protocol.SessionUpdate:
    """Return the original payload after validation by the official ACP SDK.

    Generated SDK models may omit unrecognized extension fields on serialization;
    the existing consumers need the untouched dictionary, including nested _meta.
    """
    from acp.schema import SessionNotification
    from toad.acp.notification_items import NotificationItems

    notification = SessionNotification.model_validate(
        {"sessionId": session_id, "update": update, "_meta": metadata},
        strict=True,
    )
    NotificationItems(update).dispatch_sync(notification.update)
    return cast(protocol.SessionUpdate, update)
