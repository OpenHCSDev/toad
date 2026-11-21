"""A renderer transport for Android's app-owned Python service process.

Android does not ship CPython's ``_multiprocessing``.  python-for-android services
are its process primitive, so this transport carries the same serialized
``RenderTask`` a desktop ``RenderProcessPool`` carries over one private Unix
socket.  The task and prepared-result contracts remain owned by render_backend;
only process acquisition differs.
"""

from __future__ import annotations

import asyncio
import os
import pickle
import socket
from pathlib import Path
from struct import Struct
from typing import TypeVar

from toad.render_backend import Renderer, RenderTask
from toad.render_processes import capture_submitted
from toad.work_preparation import PreparedValue

Result = TypeVar("Result")
FRAME = Struct("!Q")
SUCCESS = b"\x01"
FAILURE = b"\x00"
SHUTDOWN = 0


def _read_exact(stream: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError("Android render service closed its response")
        chunks.extend(chunk)
    return bytes(chunks)


def _read_frame(stream: socket.socket) -> bytes:
    size, = FRAME.unpack(_read_exact(stream, FRAME.size))
    return _read_exact(stream, size)


def _write_frame(stream: socket.socket, payload: bytes) -> None:
    stream.sendall(FRAME.pack(len(payload)) + payload)


def serve_render_socket(path: Path) -> None:
    """Serve serialized render tasks until the app sends the zero-length close frame."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        server.listen(4)
        while True:
            connection, _ = server.accept()
            with connection:
                size, = FRAME.unpack(_read_exact(connection, FRAME.size))
                if size == SHUTDOWN:
                    return
                submission = _read_exact(connection, size)
                try:
                    prepared = capture_submitted(submission)
                    answer = SUCCESS + pickle.dumps(prepared, protocol=5)
                except Exception as failure:  # noqa: BLE001 -- serialize the worker boundary
                    answer = FAILURE + f"{type(failure).__name__}: {failure}".encode(errors="replace")
                _write_frame(connection, answer)
    finally:
        server.close()
        path.unlink(missing_ok=True)


class SocketServiceRenderer(Renderer):
    """Bounded client of one app-private render-service socket."""

    def __init__(self, path: Path, max_pending: int = 4) -> None:
        super().__init__()
        self.path = path
        self._slots = asyncio.Semaphore(max_pending)
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def start(self) -> None:
        """The Android activity owns service startup; the first exchange waits for its socket."""

    def _connect(self, wait: bool = True) -> socket.socket:
        last: OSError | None = None
        for _ in range(100 if wait else 1):
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                client.connect(str(self.path))
                return client
            except OSError as failure:
                last = failure
                client.close()
                # This runs in asyncio.to_thread, never on the UI loop.
                import time
                time.sleep(0.05)
        raise ConnectionError(f"Android render service did not open {self.path}: {last}")

    def _exchange(self, submission: bytes) -> PreparedValue:
        with self._connect() as client:
            _write_frame(client, submission)
            answer = _read_frame(client)
        if not answer or answer[:1] != SUCCESS:
            detail = answer[1:].decode(errors="replace") if answer else "empty response"
            raise RuntimeError(f"Android render service failed: {detail}")
        return PreparedValue.accept(pickle.loads(answer[1:]))

    async def capture(self, task: RenderTask[Result]) -> PreparedValue[Result]:
        submission = await asyncio.to_thread(pickle.dumps, task, 5)
        return await self.capture_submitted(task, submission)

    async def capture_submitted(
        self, task: RenderTask[Result], submission: bytes,
    ) -> PreparedValue[Result]:
        if self._closed:
            raise RuntimeError("SocketServiceRenderer is closed")
        async with self._slots:
            return await task.complete_capture(asyncio.to_thread(self._exchange, submission))

    def _shutdown(self) -> None:
        try:
            with self._connect(wait=False) as client:
                client.sendall(FRAME.pack(SHUTDOWN))
        except ConnectionError:
            # The Android service may already have followed its activity down.
            pass

    async def aclose(self) -> None:
        self._closed = True
        await self._close_submissions()
        await asyncio.to_thread(self._shutdown)


def android_render_socket() -> Path:
    """The one private socket path shared by the activity and its service process."""
    private = os.environ.get("ANDROID_PRIVATE")
    if not private:
        raise RuntimeError("Android renderer requires ANDROID_PRIVATE")
    return Path(private) / "toad-render.sock"


class AndroidRenderService(SocketServiceRenderer):
    """Qt on Android prepares rows in its declared p4a service process."""

    def __init__(self) -> None:
        super().__init__(android_render_socket())

