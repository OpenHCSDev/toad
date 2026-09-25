"""Typed renderer messages; dictionary handling is confined to this wire boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, TypedDict, cast
from uuid import UUID

from toad.render_tasks import RENDER_TASK_TYPES, RendererResult, RendererTask


class RenderCommandKind(str, Enum):
    SUBMIT = "renderer_submit"
    POLL = "renderer_poll"
    CANCEL = "renderer_cancel"
    ACKNOWLEDGE = "renderer_acknowledge"
    RELEASE = "renderer_release"
    SHUTDOWN = "shutdown"


class RenderStatus(str, Enum):
    ACCEPTED = "accepted"
    BUSY = "busy"
    PENDING = "pending"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNKNOWN = "unknown"
    ACKNOWLEDGED = "acknowledged"


class RenderCommand(ABC):
    @property
    @abstractmethod
    def kind(self) -> RenderCommandKind:
        """Own this command's serialized identity."""


@dataclass(frozen=True)
class ClientCommand(RenderCommand):
    client_id: UUID


@dataclass(frozen=True)
class RequestCommand(ClientCommand):
    request_id: UUID


@dataclass(frozen=True)
class SubmitRender(RequestCommand):
    task: RendererTask

    @property
    def kind(self) -> RenderCommandKind:
        return RenderCommandKind.SUBMIT


@dataclass(frozen=True)
class PollRender(RequestCommand):
    @property
    def kind(self) -> RenderCommandKind:
        return RenderCommandKind.POLL


@dataclass(frozen=True)
class CancelRender(RequestCommand):
    @property
    def kind(self) -> RenderCommandKind:
        return RenderCommandKind.CANCEL


@dataclass(frozen=True)
class AcknowledgeRender(RequestCommand):
    @property
    def kind(self) -> RenderCommandKind:
        return RenderCommandKind.ACKNOWLEDGE


@dataclass(frozen=True)
class ReleaseRenderer(ClientCommand):
    @property
    def kind(self) -> RenderCommandKind:
        return RenderCommandKind.RELEASE


@dataclass(frozen=True)
class ShutdownRenderer(RenderCommand):
    @property
    def kind(self) -> RenderCommandKind:
        return RenderCommandKind.SHUTDOWN


type ClientRenderCommand = SubmitRender | PollRender | CancelRender | AcknowledgeRender | ReleaseRenderer
type RendererCommand = ClientRenderCommand | ShutdownRenderer


@dataclass(frozen=True)
class RenderReply:
    status: RenderStatus
    request_id: UUID | None = None
    result: RendererResult | None = None
    error: str | None = None
    renderer_pid: int | None = None


class RenderEnvelope(TypedDict):
    type: str
    command: RendererCommand


def encode_command(command: RendererCommand) -> RenderEnvelope:
    return RenderEnvelope(type=command.kind.value, command=command)


def decode_command(envelope: Mapping[str, object]) -> RendererCommand:
    raw_kind = envelope["type"]
    if not isinstance(raw_kind, str):
        raise TypeError("Renderer command type must be serialized text")
    kind = RenderCommandKind(raw_kind)
    if kind is RenderCommandKind.SHUTDOWN:
        return ShutdownRenderer()
    command = envelope["command"]
    match kind, command:
        case RenderCommandKind.SUBMIT, SubmitRender():
            if type(command.task) not in RENDER_TASK_TYPES:
                raise TypeError("Unsupported renderer operation class")
        case RenderCommandKind.POLL, PollRender():
            pass
        case RenderCommandKind.CANCEL, CancelRender():
            pass
        case RenderCommandKind.ACKNOWLEDGE, AcknowledgeRender():
            pass
        case RenderCommandKind.RELEASE, ReleaseRenderer():
            pass
        case _:
            raise TypeError("Renderer envelope does not match its declared command")
    decoded = cast(ClientRenderCommand, command)
    if not isinstance(decoded.client_id, UUID):
        raise TypeError("Renderer client identity must be a UUID")
    if not isinstance(decoded, ReleaseRenderer) and not isinstance(decoded.request_id, UUID):
        raise TypeError("Renderer request identity must be a UUID")
    return decoded


def decode_reply(value: object) -> RenderReply:
    if not isinstance(value, RenderReply) or not isinstance(value.status, RenderStatus):
        raise TypeError("Expected a typed renderer reply")
    return value
