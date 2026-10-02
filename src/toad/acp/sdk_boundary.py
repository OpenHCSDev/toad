"""Decode the specification once; typed SDK models own ACP values thereafter."""
from typing import Any
from acp.schema import SessionNotification, ToolCall
from agent_comms.field_codec import FieldRepresentation
from toad.acp.notification_items import NotificationItems


class ToolCallWire(FieldRepresentation):
    """The official SDK owns its external record; FieldCodec owns our envelope."""

    @classmethod
    def encode(cls, value: ToolCall) -> object:
        return value.model_dump(mode="json", by_alias=True)

    @classmethod
    def decode(cls, value: object) -> ToolCall:
        return ToolCall.model_validate(value, strict=True)

    @classmethod
    def schema(cls) -> dict:
        return ToolCall.model_json_schema(by_alias=True)


def decode_session_update(session_id: str, update: object,
                          metadata: dict[str, Any] | None = None) -> SessionNotification:
    notification = SessionNotification.model_validate(
        {"sessionId": session_id, "update": update, "_meta": metadata}, strict=True)
    NotificationItems(update).dispatch_sync(notification.update)
    return notification
