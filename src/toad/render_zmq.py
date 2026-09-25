"""Persistent renderer endpoint using ZMQRuntime's declared lifecycle/transport.

Import this optional backend only when ZMQRuntime is installed. The GUI-facing
adapter below keeps all connection and request I/O on one owned I/O thread.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import math
import os
from pathlib import Path
import subprocess
import stat
import sys
from typing import Generic, Mapping, TypeVar, cast
from uuid import UUID, uuid4

from zmqruntime import ZMQClient, ZMQConfig, ZMQServer
from zmqruntime.config import TransportMode
from zmqruntime.execution.client import ExecutionClient
from zmqruntime.messages import EndpointApplication, EndpointControlCapability, PongResponse, ResponseType
from zmqruntime.shutdown import EndpointShutdownMode

from toad.render_backend import Renderer
from toad.render_identity import RendererBuild
from toad.render_protocol import (
    AcknowledgeRender, CancelRender, PollRender, ReleaseRenderer, RenderReply, RendererCommand,
    RenderStatus, RequestCommand, ShutdownRenderer, SubmitRender, decode_command, decode_reply, encode_command,
)
from toad.render_service import RenderService, RenderServiceConfig
from toad.render_tasks import RENDER_TASK_TYPES, RendererTask, RenderTask

ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class RendererEndpoint:
    directory: Path
    version: str
    port: int = 19001

    def __post_init__(self) -> None:
        if not self.directory.is_absolute():
            raise ValueError("Renderer IPC directory must be absolute")

    def prepare_directory(self) -> None:
        """Pickle transport is restricted to the current user's private IPC path."""
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise PermissionError("Renderer IPC directory must be private and owned by this user")

    @classmethod
    def for_runtime(cls, directory: Path, config: RenderServiceConfig) -> "RendererEndpoint":
        """Resolve off-loop; incompatible builds occupy distinct IPC directories."""
        version = RendererBuild.current(config).version
        return cls(directory / version[:24], version)

    @property
    def application(self) -> EndpointApplication:
        return EndpointApplication("toad-renderer", self.version)

    @property
    def config(self) -> ZMQConfig:
        return ZMQConfig(app_name="toad-renderer", ipc_socket_dir=str(self.directory),
                         ipc_socket_prefix="render", default_port=self.port)


class RendererServer(ZMQServer):
    _server_type = "toad-renderer"

    def __init__(self, endpoint: RendererEndpoint, service_config: RenderServiceConfig) -> None:
        if RendererBuild.current(service_config).version != endpoint.version:
            raise RuntimeError("Renderer source or configuration changed before service startup")
        endpoint.prepare_directory()
        self.service = RenderService(service_config, expected_build=endpoint.version)
        super().__init__(endpoint.port, host="localhost", transport_mode=TransportMode.IPC,
                         config=endpoint.config, application=endpoint.application)

    def _create_pong_response(self) -> PongResponse:
        return replace(super()._create_pong_response(), control_capabilities=frozenset({
            EndpointControlCapability.PING, EndpointControlCapability.SHUTDOWN,
        }))

    def process_messages(self) -> None:
        self.service.reap()
        super().process_messages()

    def handle_control_message(self, message: Mapping[str, object]) -> RenderReply | dict[str, str]:
        command = decode_command(message)
        if isinstance(command, ShutdownRenderer):
            self.service.dispatch(command)
            self.request_shutdown()
            # ZMQRuntime owns this lifecycle acknowledgement's wire identity.
            return {"type": ResponseType.SHUTDOWN_ACK.value}
        return replace(self.service.dispatch(command), renderer_pid=os.getpid())

    def handle_data_message(self, message: object) -> None:
        raise TypeError("Renderer requests use the declared control boundary")


class RendererClient(ExecutionClient[RendererCommand, None]):
    def __init__(self, endpoint: RendererEndpoint, service_config: RenderServiceConfig) -> None:
        self.renderer_endpoint = endpoint
        self.service_config = service_config
        super().__init__(endpoint.port, host="localhost", persistent=True,
                         transport_mode=TransportMode.IPC, config=endpoint.config)

    def _spawn_server_process(self) -> subprocess.Popen[bytes]:
        environment = dict(os.environ)
        for name in ("AGENT_COMMS_THREAD", "PI_AGENT_ID", "PI_PROMPT"):
            environment.pop(name, None)
        config = self.service_config
        return subprocess.Popen(
            [sys.executable, "-m", "toad.render_server", "--directory", str(self.renderer_endpoint.directory),
             "--version", self.renderer_endpoint.version, "--port", str(self.port),
             "--workers", str(config.max_workers), "--pending", str(config.max_pending),
             "--client-lease", str(config.client_lease_seconds)],
            env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )

    def serialize_task(self, task: RendererCommand, config: None = None) -> dict[str, object]:
        return dict(encode_command(task))

    def send_data(self, data: RendererCommand) -> RenderReply:
        return decode_reply(self._send_control_request(self.serialize_task(data), timeout_ms=5000))

    def require_identity(self) -> None:
        observed = self.connected_endpoint
        if observed is None:
            raise RuntimeError("Renderer connection has no handshake")
        self.renderer_endpoint.application.compatibility_with(observed.application).require_match()


class RendererConnection:
    """Used only by the pool's single I/O thread, including socket teardown."""

    def __init__(self, endpoint: RendererEndpoint, config: RenderServiceConfig) -> None:
        self.endpoint, self.config = endpoint, config
        self.client: RendererClient | None = None

    def exchange(self, command: RendererCommand) -> RenderReply:
        if self.client is None:
            self.endpoint.prepare_directory()
            client = RendererClient(self.endpoint, self.config)
            try:
                if not client.connect(timeout=10):
                    raise RuntimeError("Persistent renderer did not become ready")
                client.require_identity()
            except BaseException:
                client.disconnect()
                raise
            self.client = client
        reply = self.client.send_data(command)
        if isinstance(command, RequestCommand) and reply.request_id != command.request_id:
            raise RuntimeError("Renderer reply belongs to a different request")
        return reply

    def release(self, client_id: UUID) -> None:
        """Best-effort teardown on the I/O thread; never spawn during cleanup."""
        if self.client is not None:
            try:
                self.client.send_data(ReleaseRenderer(client_id))
            except Exception:
                # Once all client traffic stops, the service lease reclaims work.
                pass

    def close(self) -> None:
        if self.client is not None:
            self.client.disconnect()
            self.client = None


@dataclass
class RenderSubmission(Generic[ResultT]):
    request_id: UUID
    task: RenderTask[ResultT]
    cancel_requested: bool = False


class RendererSessionFailed(RuntimeError):
    """An uncertain transport outcome ends this client lease; use a new client."""


class PersistentRendererPool(Renderer):
    """Bounded async client; closing it leaves compatible CPU workers warm."""

    def __init__(
        self, endpoint: RendererEndpoint, config: RenderServiceConfig = RenderServiceConfig(),
        *, poll_interval: float = 0.01,
    ) -> None:
        if isinstance(poll_interval, bool) or not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("Renderer polling interval must be positive")
        self.endpoint, self.config = endpoint, config
        self._client_id = uuid4()
        self._connection = RendererConnection(endpoint, config)
        self._io = ThreadPoolExecutor(max_workers=1, thread_name_prefix="render-transport")
        self._poll_interval = poll_interval
        self._pending: set[asyncio.Task[object]] = set()
        self._changed = asyncio.Event()
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._failure: Exception | None = None

    def _bind_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("Renderer client must use its owning event loop")
        return loop

    async def _exchange(self, command: RendererCommand) -> RenderReply:
        if self._failure is not None:
            raise RendererSessionFailed("Renderer client session failed") from self._failure
        try:
            return await self._bind_loop().run_in_executor(self._io, self._connection.exchange, command)
        except Exception as error:
            # Do not keep renewing this lease while a lost response may have left
            # untracked accepted work. Other admitted requests fail on their next
            # exchange; cleanup releases them, or the stopped lease expires.
            self._failure = error
            self._changed.set()
            raise RendererSessionFailed("Renderer client session failed") from error

    def _finished(self, task: asyncio.Task[object]) -> None:
        self._pending.discard(task)
        if not task.cancelled():
            task.exception()
        self._changed.set()

    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        self._bind_loop()
        if type(task) not in RENDER_TASK_TYPES:
            raise TypeError("Unsupported persistent rendering task class")
        while not self._closed and self._failure is None and len(self._pending) >= self.config.max_pending:
            self._changed.clear()
            await self._changed.wait()
        if self._closed:
            raise RuntimeError("Renderer client is closed")
        if self._failure is not None:
            raise RendererSessionFailed("Renderer client session failed") from self._failure
        submission = RenderSubmission(uuid4(), task)
        running = asyncio.create_task(self._run(submission), name="persistent-render-request")
        tracked = cast(asyncio.Task[object], running)
        self._pending.add(tracked)
        tracked.add_done_callback(self._finished)
        try:
            await asyncio.wait((running,))
        except asyncio.CancelledError:
            submission.cancel_requested = True
            raise
        return running.result()

    async def _run(self, submission: RenderSubmission[ResultT]) -> ResultT:
        request_id = submission.request_id
        task = cast(RendererTask, submission.task)
        while True:
            if self._closed or submission.cancel_requested:
                raise asyncio.CancelledError
            reply = await self._exchange(SubmitRender(self._client_id, request_id, task))
            if reply.status is RenderStatus.ACCEPTED:
                break
            if reply.status is not RenderStatus.BUSY:
                raise RuntimeError(reply.error or "Renderer rejected submission")
            await asyncio.sleep(self._poll_interval)
        cancellation_sent = False
        while True:
            if (submission.cancel_requested or self._closed) and not cancellation_sent:
                await self._exchange(CancelRender(self._client_id, request_id))
                cancellation_sent = True
            reply = await self._exchange(PollRender(self._client_id, request_id))
            if reply.status is RenderStatus.PENDING:
                await asyncio.sleep(self._poll_interval)
                continue
            if reply.status is RenderStatus.UNKNOWN:
                raise RuntimeError("Renderer no longer owns the submitted request")
            await self._exchange(AcknowledgeRender(self._client_id, request_id))
            if reply.status is RenderStatus.CANCELLED or submission.cancel_requested or self._closed:
                raise asyncio.CancelledError
            if reply.status is RenderStatus.FAILED:
                raise RuntimeError(reply.error or "Renderer preparation failed")
            if reply.status is not RenderStatus.COMPLETE:
                raise RuntimeError("Unexpected renderer lifecycle result")
            return submission.task.accept_result(reply.result)

    async def aclose(self) -> None:
        self._bind_loop()
        self._closed = True
        self._changed.set()
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="persistent-render-close")
        await asyncio.wait((self._close_task,))
        self._close_task.result()

    async def _close(self) -> None:
        try:
            if self._pending:
                await asyncio.gather(*tuple(self._pending), return_exceptions=True)
            await self._bind_loop().run_in_executor(self._io, self._connection.release, self._client_id)
        finally:
            await self._bind_loop().run_in_executor(self._io, self._connection.close)
            await asyncio.to_thread(self._io.shutdown, wait=True, cancel_futures=True)

    async def shutdown_service(self) -> bool:
        """Explicit owner/test teardown; normal aclose deliberately preserves it."""
        result = await asyncio.to_thread(
            ZMQClient.shutdown_endpoint_on_port, self.endpoint.port, EndpointShutdownMode.GRACEFUL,
            timeout=10, transport_mode=TransportMode.IPC, config=self.endpoint.config,
        )
        return result.succeeded
