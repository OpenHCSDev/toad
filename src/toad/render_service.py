"""Bounded renderer execution authority; transport-independent typed commands."""

from __future__ import annotations

from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
import multiprocessing
import math
import time
from uuid import UUID

from toad.render_processes import _initialize_worker
from toad.render_protocol import (
    AcknowledgeRender,
    CancelRender,
    PollRender,
    ReleaseRender,
    RenderReply,
    ShutdownRender,
    SubmitRender,
    AcceptedReply,
    UnknownReply,
    BusyReply,
    PendingReply,
    CancelledReply,
    FailedReply,
    RejectedReply,
    CompleteReply,
    AcknowledgedReply,
    CapturedResult,
)


@dataclass(frozen=True)
class RenderServiceConfig:
    max_workers: int = 2
    max_pending: int = 4
    client_lease_seconds: float = 60.0

    def __post_init__(self) -> None:
        if (any(type(value) is not int or value < 1 for value in (self.max_workers, self.max_pending))
                or isinstance(self.client_lease_seconds, bool)
                or not math.isfinite(self.client_lease_seconds) or self.client_lease_seconds <= 0):
            raise ValueError("Renderer capacities and client lease must be positive")


def _initialize_render_worker(config: RenderServiceConfig, expected_build: str | None) -> None:
    """Lazy-spawned workers must still match the service's advertised build."""
    _initialize_worker()
    if expected_build is not None:
        from toad.render_identity import RendererBuild

        if RendererBuild.current(config).version != expected_build:
            raise RuntimeError("Renderer source changed before worker startup")


@dataclass
class PendingRender:
    client_id: UUID
    future: Future[object]
    cancelled: bool = False
    abandoned: bool = False


class RenderService:
    """One command-thread owner of admission and result retention.

    Cancellation never frees running work early. Completed results remain until
    acknowledged, so a transport retry cannot silently lose a final response.
    Expired clients abandon delivery; CPU admission is released only on completion.
    """

    def __init__(self, config: RenderServiceConfig, *, expected_build: str | None = None) -> None:
        self.config = config
        self._executor = ProcessPoolExecutor(
            max_workers=config.max_workers, mp_context=multiprocessing.get_context("spawn"),
            initializer=_initialize_render_worker, initargs=(config, expected_build),
        )
        self._jobs: dict[UUID, PendingRender] = {}
        self._clients: dict[UUID, float] = {}
        self._closed = False

    @property
    def pending_count(self) -> int:
        return len(self._jobs)

    def reap(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        expired = [client for client, seen in self._clients.items()
                   if current - seen >= self.config.client_lease_seconds]
        for client in expired:
            self._abandon(client)
        for request_id, job in tuple(self._jobs.items()):
            if job.abandoned and job.future.done():
                self._jobs.pop(request_id)

    def _touch(self, client_id: UUID) -> None:
        self._clients[client_id] = time.monotonic()

    def _abandon(self, client_id: UUID) -> None:
        self._clients.pop(client_id, None)
        for job in self._jobs.values():
            if job.client_id == client_id:
                job.abandoned = job.cancelled = True
                job.future.cancel()

    def _owned(self, client_id: UUID, request_id: UUID) -> PendingRender | None:
        self._touch(client_id)
        job = self._jobs.get(request_id)
        return job if job is not None and job.client_id == client_id else None

    def submit(self, command: SubmitRender) -> RenderReply:
        if self._closed:
            return RejectedReply(command.request_id, "Renderer is closed")
        self.reap()
        self._touch(command.client_id)
        existing = self._jobs.get(command.request_id)
        if existing is not None:
            return (
                AcceptedReply(command.request_id)
                if existing.client_id == command.client_id
                else UnknownReply(command.request_id)
            )
        if len(self._jobs) >= self.config.max_pending:
            return BusyReply(command.request_id)
        future: Future[object] = self._executor.submit(command.task.execute)
        self._jobs[command.request_id] = PendingRender(command.client_id, future)
        return AcceptedReply(command.request_id)

    def poll(self, command: PollRender) -> RenderReply:
        job = self._owned(command.client_id, command.request_id)
        if job is None:
            return UnknownReply(command.request_id)
        if not job.future.done():
            return PendingReply(command.request_id)
        if job.cancelled or job.future.cancelled():
            return CancelledReply(command.request_id)
        try:
            result = job.future.result()
        except Exception as error:
            return FailedReply(command.request_id, f"{type(error).__name__}: {error}")
        return CompleteReply(command.request_id, CapturedResult(result))

    def cancel(self, command: CancelRender) -> RenderReply:
        job = self._owned(command.client_id, command.request_id)
        if job is None:
            return UnknownReply(command.request_id)
        job.cancelled = True
        job.future.cancel()
        return AcknowledgedReply(command.request_id)

    def acknowledge(self, command: AcknowledgeRender) -> RenderReply:
        job = self._owned(command.client_id, command.request_id)
        if job is not None:
            if not job.future.done():
                return PendingReply(command.request_id)
            self._jobs.pop(command.request_id)
        return AcknowledgedReply(command.request_id)

    def release(self, command: ReleaseRender) -> RenderReply:
        self._abandon(command.client_id)
        self.reap()
        return AcknowledgedReply()

    def shutdown(self, command: ShutdownRender) -> RenderReply:
        self._closed = True
        return AcknowledgedReply()

    def close(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._jobs.clear()
        self._clients.clear()
