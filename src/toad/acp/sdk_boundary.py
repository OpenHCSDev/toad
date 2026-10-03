"""Decode the specification once; typed SDK models own ACP values thereafter."""
from __future__ import annotations
from typing import Any, TYPE_CHECKING
from abc import abstractmethod
from dataclasses import dataclass
from agent_comms.declared_family import DeclaredFamily
from toad.render_backend import RenderTask
from acp.schema import SessionNotification, ToolCall
from agent_comms.field_codec import FieldRepresentation
from toad.acp.notification_items import NotificationItems

if TYPE_CHECKING:
    from toad.acp.status import ToolCallStatus


class ToolCallWire(FieldRepresentation):
    """The SDK's status selects its existing nominal owner once at ingress."""

    @classmethod
    def encode(cls, value: ToolCallStatus) -> object:
        return value.call.model_dump(mode="json", by_alias=True)

    @classmethod
    def decode(cls, value: object) -> ToolCallStatus:
        from toad.acp.status import ToolCallStatus
        return ToolCallStatus.from_acp(ToolCall.model_validate(value, strict=True))

    @classmethod
    def schema(cls) -> dict:
        return ToolCall.model_json_schema(by_alias=True)


def decode_session_update(session_id: str, update: object,
                          metadata: dict[str, Any] | None = None) -> SessionNotification:
    notification = SessionNotification.model_validate(
        {"sessionId": session_id, "update": update, "_meta": metadata}, strict=True)
    NotificationItems(update).dispatch_sync(notification.update)
    return notification


class SessionUpdateValidation(DeclaredFamily, affix='SessionUpdateValidation'):
    @abstractmethod
    def publish(self, owner, session_id, raw, metadata): ...


@dataclass(frozen=True)
class AcceptedSessionUpdateValidation(SessionUpdateValidation):
    notification: SessionNotification

    def publish(self, owner, session_id, raw, metadata):
        owner.publish(session_id, self.notification)


@dataclass(frozen=True)
class RejectedSessionUpdateValidation(SessionUpdateValidation):
    error: str

    def publish(self, owner, session_id, raw, metadata):
        owner.reject(session_id, raw, metadata, self.error)


@dataclass(frozen=True)
class ValidateSessionUpdateTask(RenderTask[SessionUpdateValidation]):
    """Keep the official SDK's validator graph in process workers, not the UI."""

    session_id: str
    update: object
    metadata: dict | None = None

    def execute(self) -> SessionUpdateValidation:
        try:
            notification = decode_session_update(self.session_id, self.update, self.metadata)
        except (ValueError, TypeError) as error:
            return RejectedSessionUpdateValidation(str(error))
        return AcceptedSessionUpdateValidation(notification)

    def accept_result(self, result: object) -> SessionUpdateValidation:
        if not isinstance(result, SessionUpdateValidation):
            raise TypeError("ACP validation worker returned an invalid result")
        return result
