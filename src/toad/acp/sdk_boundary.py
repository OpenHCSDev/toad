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
from agent_comms.acp_extension import AgentCommsUpdate, decode_updates

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


class SessionUpdateValidation(DeclaredFamily, affix='SessionUpdateValidation'):
    @abstractmethod
    def publish(self, owner, session_id, raw, metadata): ...


@dataclass(frozen=True)
class AcceptedSessionUpdateValidation(SessionUpdateValidation):
    notification: SessionNotification
    updates: tuple[AgentCommsUpdate, ...]

    def publish(self, owner, session_id, raw, metadata):
        owner.publish(session_id, self.notification, self.updates)


@dataclass(frozen=True)
class RejectedSessionUpdateValidation(SessionUpdateValidation):
    error: str

    def publish(self, owner, session_id, raw, metadata):
        owner.reject(session_id, raw, metadata, self.error)


@dataclass(frozen=True)
class ValidateSessionUpdateTask(RenderTask[SessionUpdateValidation]):
    """Check complete plans and decode Comms metadata after SDK protocol decoding."""

    notification: SessionNotification
    raw_update: dict

    def execute(self) -> SessionUpdateValidation:
        try:
            NotificationItems(self.raw_update).dispatch_sync(self.notification.update)
            updates = decode_updates(self.notification.update.field_meta)
        except (ValueError, TypeError) as error:
            return RejectedSessionUpdateValidation(str(error))
        return AcceptedSessionUpdateValidation(self.notification, updates)


@dataclass(frozen=True)
class DecodeCommsMetadataTask(RenderTask[tuple[AgentCommsUpdate, ...]]):
    """Request metadata uses the same strict Comms ingress in owned workers."""

    metadata: object

    def execute(self) -> tuple[AgentCommsUpdate, ...]:
        return decode_updates(self.metadata)
