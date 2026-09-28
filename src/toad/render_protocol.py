"""Declaration-derived renderer envelopes and reply-owned client transitions."""

from __future__ import annotations

import asyncio
import pickle
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec
from toad.render_tasks import RenderTask

if TYPE_CHECKING:
    from toad.render_service import RenderService
    from toad.render_zmq import PersistentRendererPool, RenderSubmission


class RenderCodec(FieldCodec):
    """UUIDs and captured dependency objects extend the existing record codec.

    Markdown tokens and Rich/Textual results use their existing pickle contract.
    Only the renderer's private owner-only IPC directory accepts these captures.
    """

    @classmethod
    def encode(cls, value):
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, CapturedResult):
            return pickle.dumps(value.value, protocol=pickle.HIGHEST_PROTOCOL)
        if isinstance(value, RenderTask):
            return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        return super().encode(value)

    @staticmethod
    def _capture(data: object) -> object:
        if not isinstance(data, bytes):
            raise ValueError("Expected a captured renderer byte payload")
        return pickle.loads(data)

    @classmethod
    def _decode(cls, target, data):
        if target is UUID:
            return UUID(FieldCodec.decode(str, data))
        if target is CapturedResult:
            return CapturedResult(cls._capture(data))
        if target is RenderTask:
            task = cls._capture(data)
            if type(task) not in RenderTask.members_with(RenderTask):
                raise TypeError("Expected a declared rendering task")
            return task
        return super()._decode(target, data)


@dataclass(frozen=True)
class CapturedResult:
    value: object


class RenderCommandTransport(ABC):
    @abstractmethod
    def execute(self, service: RenderService) -> RenderReply: ...

    async def exchange(self, client: PersistentRendererPool, submission: RenderSubmission) -> RenderReply:
        return await client._exchange(self)



class RenderCommand(RenderCommandTransport, DeclaredFamily, affix="Render"):
    family_discriminator = "type"

@dataclass(frozen=True)
class ClientCommand(RenderCommand):
    client_id: UUID


@dataclass(frozen=True)
class RequestCommand(ClientCommand):
    request_id: UUID


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
    task: RenderTask

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
    request_id: UUID

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
    result: CapturedResult

    async def advance(self, submission, client):
        await client.acknowledge(submission)
        submission.result.set_result(submission.task.accept_result(self.result.value))
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
    request_id: UUID | None = None

    def request_identity(self):
        return self.request_id

    async def advance(self, submission, client):
        raise RuntimeError("Unexpected renderer lifecycle acknowledgement")
