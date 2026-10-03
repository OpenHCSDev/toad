"""Declaration-derived renderer envelopes and reply-owned client transitions."""

from __future__ import annotations

import asyncio
import pickle
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, TYPE_CHECKING
from uuid import UUID

from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldRepresentation
from toad.render_backend import RenderTask

if TYPE_CHECKING:
    from toad.render_service import RenderService
    from toad.render_zmq import PersistentRendererPool, RenderSubmission


@dataclass(frozen=True)
class CapturedResult:
    value: object


class RendererIdentity(FieldRepresentation):
    """The private ZMQ transport carries UUID objects without JSON coercion."""

    @classmethod
    def encode(cls, value):
        if not isinstance(value, UUID):
            raise TypeError("Expected a renderer UUID")
        return value

    @classmethod
    def decode(cls, value):
        return cls.encode(value)


class RendererCapture(FieldRepresentation):
    """Only explicitly declared fields accept the private pickle contract."""

    @classmethod
    def encode(cls, value):
        return pickle.dumps(cls.capture(value), protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def decode(cls, value):
        if not isinstance(value, bytes):
            raise ValueError("Expected a captured renderer byte payload")
        return cls.restore(pickle.loads(value))

    @classmethod
    @abstractmethod
    def capture(cls, value: object) -> object: ...

    @classmethod
    @abstractmethod
    def restore(cls, value: object) -> object: ...


class TaskCapture(RendererCapture):
    @classmethod
    def capture(cls, value):
        return cls.restore(value)

    @classmethod
    def restore(cls, value):
        if type(value) not in RenderTask.members_with(RenderTask):
            raise TypeError("Expected a declared rendering task")
        return value


class ResultCapture(RendererCapture):
    @classmethod
    def capture(cls, value):
        if not isinstance(value, CapturedResult):
            raise TypeError("Expected a captured rendering result")
        return value.value

    @classmethod
    def restore(cls, value):
        return CapturedResult(value)


RenderIdentity = Annotated[UUID, RendererIdentity]


class RenderCommandTransport(ABC):
    @abstractmethod
    def execute(self, service: RenderService) -> RenderReply: ...

    async def exchange(self, client: PersistentRendererPool, submission: RenderSubmission) -> RenderReply:
        return await client._exchange(self)



class RenderCommand(RenderCommandTransport, DeclaredFamily, affix="Render"):
    family_discriminator = "type"

@dataclass(frozen=True)
class ClientCommand(RenderCommand):
    client_id: RenderIdentity


@dataclass(frozen=True)
class RequestCommand(ClientCommand):
    request_id: RenderIdentity


class InitialRenderRequest(RequestCommand):
    async def exchange(self, client, submission):
        if client._closed or submission.cancel_requested:
            raise asyncio.CancelledError
        return await super().exchange(client, submission)



class RetainedRenderRequest(RequestCommand):
    async def exchange(self, client, submission):
        if (submission.cancel_requested or client._closed) and not submission.cancellation_sent:
            await client._exchange(CancelRender(self.client_id, self.request_id))
            submission.cancellation_sent = True
        return await super().exchange(client, submission)



@dataclass(frozen=True)
class SubmitRender(InitialRenderRequest):
    task: Annotated[RenderTask, TaskCapture]

    def execute(self, service):
        return service.submit(self)

@dataclass(frozen=True)
class PollRender(RetainedRenderRequest):
    def execute(self, service):
        return service.poll(self)

@dataclass(frozen=True)
class CancelRender(RequestCommand):
    def execute(self, service):
        return service.cancel(self)


@dataclass(frozen=True)
class AcknowledgeRender(RequestCommand):
    def execute(self, service):
        return service.acknowledge(self)


@dataclass(frozen=True)
class ReleaseRender(ClientCommand):
    def execute(self, service):
        return service.release(self)


@dataclass(frozen=True)
class ShutdownRender(RenderCommand):
    def execute(self, service):
        return service.shutdown(self)


class RenderReplyProgression(ABC):
    def request_identity(self) -> UUID | None:
        return None

    @abstractmethod
    async def advance(self, submission: RenderSubmission, client: PersistentRendererPool) -> RenderCommand | None: ...



@dataclass(frozen=True, kw_only=True)
class RenderReply(RenderReplyProgression, DeclaredFamily, affix="Reply"):
    renderer_pid: int | None = None

@dataclass(frozen=True)
class RequestReply(RenderReply):
    request_id: RenderIdentity

    def request_identity(self) -> UUID:
        return self.request_id


@dataclass(frozen=True)
class AcceptedReply(RequestReply):
    async def advance(self, submission, client):
        return PollRender(client._client_id, submission.request_id)


@dataclass(frozen=True)
class BusyReply(RequestReply):
    async def advance(self, submission, client):
        await asyncio.sleep(client._poll_interval)
        return SubmitRender(client._client_id, submission.request_id, submission.task)


@dataclass(frozen=True)
class PendingReply(RequestReply):
    async def advance(self, submission, client):
        await asyncio.sleep(client._poll_interval)
        return PollRender(client._client_id, submission.request_id)


@dataclass(frozen=True)
class CompleteReply(RequestReply):
    result: Annotated[CapturedResult, ResultCapture]

    async def advance(self, submission, client):
        await client.acknowledge(submission)
        submission.result.set_result(self.result.value)
        return None


@dataclass(frozen=True)
class CancelledReply(RequestReply):
    async def advance(self, submission, client):
        await client.acknowledge(submission)
        raise asyncio.CancelledError


@dataclass(frozen=True)
class FailedReply(RequestReply):
    error: str

    async def advance(self, submission, client):
        await client.acknowledge(submission)
        raise RuntimeError(self.error)


@dataclass(frozen=True)
class RejectedReply(FailedReply):
    async def advance(self, submission, client):
        raise RuntimeError(self.error)


@dataclass(frozen=True)
class UnknownReply(RequestReply):
    async def advance(self, submission, client):
        raise RuntimeError("Renderer no longer owns the submitted request")


@dataclass(frozen=True)
class AcknowledgedReply(RenderReply):
    request_id: Annotated[UUID | None, RendererIdentity] = None

    def request_identity(self):
        return self.request_id

    async def advance(self, submission, client):
        raise RuntimeError("Unexpected renderer lifecycle acknowledgement")
