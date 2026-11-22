"""A renderer whose workers are forked from this process.

Toad prepares what it draws in another process because CPython has one interpreter lock:
work on a thread takes turns with the UI. A desktop gets that process from
``multiprocessing`` (``RenderProcessPool``). Android has no ``_multiprocessing`` (bionic has
no named semaphores), and a python-for-android service is a fresh interpreter that has to
import the application again, which took minutes on a phone and was why its row rendering
went back to a thread of the UI process.

A fork needs neither. The child is this process's own memory at the moment of the fork,
with every module the application has loaded, so it starts in the time of a system call and
imports nothing. It keeps one socket to its parent and serves the same pickled ``RenderTask``
a ``RenderProcessPool`` worker receives; the task and prepared-result contracts stay owned
by ``render_backend``, and only how the process is acquired differs.

What the child must never do is touch anything that belonged to the threads it did not
inherit: Qt, the Java runtime, the event loop. It runs render tasks, which are data in and
data out, and leaves by ``os._exit`` so no destructor of the parent's objects runs in it.
"""

from __future__ import annotations

import asyncio
import gc
import os
import pickle
import signal
import socket
import threading
from struct import Struct
from typing import TypeVar

from toad.render_backend import Renderer, RenderTask, capture_submitted
from toad.work_preparation import PreparedValue

Result = TypeVar("Result")
FRAME = Struct("!Q")
SUCCESS = b"\x01"
FAILURE = b"\x00"


class RenderChildLost(ConnectionError):
    """A forked render child closed its socket: it died, or was killed with the app."""


def _read_exact(stream: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.recv(size - len(chunks))
        if not chunk:
            raise RenderChildLost("The render child's socket closed")
        chunks.extend(chunk)
    return bytes(chunks)


def _read_frame(stream: socket.socket) -> bytes:
    size, = FRAME.unpack(_read_exact(stream, FRAME.size))
    return _read_exact(stream, size)


def _write_frame(stream: socket.socket, payload: bytes) -> None:
    stream.sendall(FRAME.pack(len(payload)) + payload)


def _serve(stream: socket.socket) -> None:
    """The child's whole life: one task in, one prepared result out, until its parent closes
    the socket (asked to stop, or gone)."""
    while True:
        try:
            submission = _read_frame(stream)
        except (RenderChildLost, OSError):
            return
        try:
            answer = SUCCESS + pickle.dumps(capture_submitted(submission), protocol=5)
        except Exception as failure:  # noqa: BLE001 -- the failure crosses the process boundary as text
            answer = FAILURE + f"{type(failure).__name__}: {failure}".encode(errors="replace")
        try:
            _write_frame(stream, answer)
        except OSError:
            return


class RenderChild:
    """One forked child and the socket to it. It prepares one task at a time."""

    def __init__(self) -> None:
        ours, theirs = socket.socketpair()
        # A collection in the child would finalize copies of the parent's objects there
        # (a Qt wrapper's destructor, in a process that has none of Qt's threads): nothing
        # the parent holds is collectable in the child, and the child collects nothing.
        gc.freeze()
        pid = os.fork()
        if pid == 0:
            status = 1
            try:
                self._become_child(theirs)
                _serve(theirs)
                status = 0
            finally:
                os._exit(status)
        gc.unfreeze()
        theirs.close()
        self.pid = pid
        self.stream = ours
        self.busy = threading.Lock()

    @staticmethod
    def _become_child(stream: socket.socket) -> None:
        """Keep the one socket and the standard streams; every other descriptor is the
        parent's (its bus connections, Qt's and Android's), and a copy held here would keep
        each open after the parent closed it."""
        gc.disable()
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGPIPE):
            signal.signal(number, signal.SIG_DFL)
        keep = stream.fileno()
        limit = min(os.sysconf("SC_OPEN_MAX"), 1 << 16)
        os.closerange(3, keep)
        os.closerange(keep + 1, limit)

    def exchange(self, submission: bytes) -> PreparedValue:
        """One task prepared in the child; called on a worker thread, which waits in the
        socket with the interpreter lock released."""
        with self.busy:
            _write_frame(self.stream, submission)
            answer = _read_frame(self.stream)
        if answer[:1] != SUCCESS:
            raise RuntimeError(f"The render child failed: {answer[1:].decode(errors='replace')}")
        return PreparedValue.accept(pickle.loads(answer[1:]))

    def close(self) -> None:
        """Closing the socket is the child's signal to leave; it is then reaped."""
        self.stream.close()
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass


class ForkedRenderer(Renderer):
    """Render tasks prepared in children forked from this process once the application's
    modules are loaded (``start``). Tasks beyond the children's number wait their turn."""

    def __init__(self, children: int = 2) -> None:
        super().__init__()
        self.count = children
        self._children: asyncio.Queue[RenderChild] = asyncio.Queue()
        self._started: list[RenderChild] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def start(self) -> None:
        """Fork the children now: they carry every module loaded so far and import nothing."""
        for _ in range(self.count):
            self._add_child()

    def _add_child(self) -> None:
        child = RenderChild()
        self._started.append(child)
        self._children.put_nowait(child)

    async def capture(self, task: RenderTask[Result]) -> PreparedValue[Result]:
        submission = await asyncio.to_thread(pickle.dumps, task, 5)
        return await self.capture_submitted(task, submission)

    async def capture_submitted(
        self, task: RenderTask[Result], submission: bytes,
    ) -> PreparedValue[Result]:
        if self._closed:
            raise RuntimeError("ForkedRenderer is closed")
        child = await self._children.get()
        try:
            return await task.complete_capture(asyncio.to_thread(child.exchange, submission))
        except RenderChildLost:
            # The task fails loudly; the next one is served by a child forked in its place.
            self._started.remove(child)
            child.close()
            child = None
            if not self._closed:
                self._add_child()
            raise
        finally:
            # A task that failed in the child, or was cancelled here, leaves the child serving.
            if child is not None:
                self._children.put_nowait(child)

    async def aclose(self) -> None:
        self._closed = True
        await self._close_submissions()
        children, self._started = self._started, []
        await asyncio.to_thread(lambda: [child.close() for child in children])
