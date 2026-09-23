"""Bounded, app-owned CPU workers for data-only rendering preparation.

Callables must be importable module-level functions; arguments and results must
be picklable data, never widgets, apps, or core services. Spawn entry points must
use the usual ``if __name__ == "__main__"`` guard. Importing this module or
constructing a pool starts no processes.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
from typing import Any, TypeVar


Result = TypeVar("Result")


def _initialize_worker() -> None:
    """CPU workers have no agent identity and do not manage external owners."""
    os.environ.pop("PI_AGENT_ID", None)
    os.environ.pop("AGENT_COMMS_THREAD", None)


class RenderProcessPool:
    """A lazy, single-event-loop process pool with bounded submitted work.

    ``max_pending`` includes both queued and running jobs, even when their
    callers have been canceled. Cancellation discards delivery to that caller;
    it does not stop CPU work or free its slot early. There is no local execution
    fallback. The application must await ``aclose()`` before closing its loop.

    Shutdown rejects new work, wakes admission waiters, cancels jobs which have
    not started, and joins running jobs off-loop. Running functions must finish:
    shutdown is graceful, not a hard timeout or forced process termination.
    Canceling an aclose waiter leaves the owned shutdown task running; another
    aclose call can await the same teardown.
    """

    def __init__(self, max_workers: int = 2, max_pending: int = 4) -> None:
        for name, value in (("max_workers", max_workers), ("max_pending", max_pending)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self._max_workers = max_workers
        self._max_pending = max_pending
        self._executor: ProcessPoolExecutor | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: set[asyncio.Future[Any]] = set()
        self._changed = asyncio.Event()
        self._closed = False
        self._shutdown: asyncio.Task[None] | None = None

    @staticmethod
    def prepare_spawn() -> None:
        """Initialize POSIX spawn bookkeeping before a UI captures stderr.

        Python 3.14's resource tracker inherits stderr's file descriptor on
        first startup. Older Textual captures report -1 instead of raising
        UnsupportedOperation, which is invalid in spawn's pass-fd list. An
        application calls this before entering terminal mode; CPU worker
        creation remains lazy. The tracker is multiprocessing-owned and is
        shared with any other process pools in this interpreter.
        """
        if os.name == "posix":
            from multiprocessing import resource_tracker

            resource_tracker.ensure_running()

    @property
    def closed(self) -> bool:
        """Whether shutdown has begun (and further submissions are rejected)."""
        return self._closed

    def _bind_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("RenderProcessPool must be used on its owning event loop")
        return loop

    def _finished(self, future: asyncio.Future[Any]) -> None:
        self._pending.discard(future)
        # Retrieve errors even when the original caller abandoned its result.
        if not future.cancelled():
            future.exception()
        self._changed.set()

    async def run(self, function: Callable[..., Result], *args: Any) -> Result:
        """Execute a data-only function in a child, propagating its result/error."""
        loop = self._bind_loop()
        while not self._closed and len(self._pending) >= self._max_pending:
            self._changed.clear()
            await self._changed.wait()
        if self._closed:
            raise RuntimeError("RenderProcessPool is closed")
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=self._max_workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_initialize_worker,
            )
        # No await between admission and registration: admission is atomic on
        # the owning loop. Waiting never propagates caller cancellation to the
        # underlying future (or logs an abandoned exception via shield).
        future = asyncio.wrap_future(self._executor.submit(function, *args), loop=loop)
        self._pending.add(future)
        future.add_done_callback(self._finished)
        await asyncio.wait((future,))
        return future.result()

    async def aclose(self) -> None:
        """Asynchronously join this pool; safe to call concurrently or repeatedly."""
        self._bind_loop()
        self._closed = True
        self._changed.set()
        if self._executor is None:
            return
        if self._shutdown is None:
            self._shutdown = asyncio.create_task(self._join(), name="render-process-shutdown")
        await asyncio.wait((self._shutdown,))
        self._shutdown.result()

    async def _join(self) -> None:
        assert self._executor is not None
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True)
        # Drain result callbacks before teardown is reported complete.
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
