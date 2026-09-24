"""Lazy application-owned adapter for the optional persistent renderer backend."""

import asyncio
from pathlib import Path
from typing import TypeVar

from toad.render_backend import Renderer
from toad.render_service import RenderServiceConfig
from toad.render_tasks import MarkdownRenderTask, PatchRenderTask, RenderTask
from toad.render_zmq import PersistentRendererPool, RendererEndpoint, RendererSessionFailed

ResultT = TypeVar("ResultT")


def _observe(task: asyncio.Task[ResultT]) -> None:
    if not task.cancelled():
        task.exception()


class PersistentRenderer(Renderer):
    """Construct synchronously; resolve code identity and connect only on demand.

    Initializing and retiring a client are owned operations, independent of any
    single widget waiter. A failed request is reported, never silently replayed;
    later requests may attach through a new client after the old one is drained.
    """

    def __init__(self, directory: Path, config: RenderServiceConfig = RenderServiceConfig()) -> None:
        self.directory, self.config = directory, config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._initialization: asyncio.Task[PersistentRendererPool] | None = None
        self._retirement: asyncio.Task[None] | None = None
        self._shutdown: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def resolved_pool(self) -> PersistentRendererPool | None:
        """The actual resolved backend, or None before successful initialization."""
        task = self._initialization
        if task is None or not task.done() or task.cancelled() or task.exception() is not None:
            return None
        return task.result()

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif loop is not self._loop:
            raise RuntimeError("PersistentRenderer must use its owning event loop")

    async def _initialize(self) -> PersistentRendererPool:
        endpoint = await asyncio.to_thread(RendererEndpoint.for_runtime, self.directory, self.config)
        return PersistentRendererPool(endpoint, self.config)

    async def _get_pool(self) -> PersistentRendererPool:
        self._bind_loop()
        retirement = self._retirement
        if retirement is not None:
            await asyncio.wait((retirement,))
            retirement.result()
            if self._retirement is retirement:
                self._retirement = None
        if self._closed:
            raise RuntimeError("Persistent renderer is closed")
        if self._initialization is None:
            self._initialization = asyncio.create_task(self._initialize(), name="renderer-initialize")
            self._initialization.add_done_callback(_observe)
        initialization = self._initialization
        await asyncio.wait((initialization,))
        if self._closed:
            raise RuntimeError("Persistent renderer is closed")
        try:
            return initialization.result()
        except Exception:
            if self._initialization is initialization:
                self._initialization = None
            raise

    def _retire(self, pool: PersistentRendererPool) -> None:
        if self.resolved_pool is pool:
            self._initialization = None
            self._retirement = asyncio.create_task(pool.aclose(), name="renderer-retire-failed-client")
            self._retirement.add_done_callback(_observe)

    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        pool = await self._get_pool()
        try:
            return await pool.submit(task)
        except RendererSessionFailed:
            self._retire(pool)
            raise

    async def warm_up(self, *, project: Path, ansi: bool, dark: bool) -> None:
        """Start compatible workers and common parser/highlighter imports off-loop.

        These small, data-only tasks use normal admission and cancellation. No
        source files are opened, no user history is fetched and nothing is mounted.
        """
        await asyncio.gather(
            self.submit(MarkdownRenderTask(
                "```python\npass\n```\n\n```json\n{}\n```\n", str(project), ansi, dark,
            )),
            self.submit(PatchRenderTask(
                "--- warmup.py\n+++ warmup.py\n@@ -1 +1 @@\n-pass\n+value = 1\n", ansi, dark,
            )),
        )

    async def aclose(self) -> None:
        self._bind_loop()
        self._closed = True
        if self._shutdown is None:
            self._shutdown = asyncio.create_task(self._close(), name="renderer-runtime-close")
            self._shutdown.add_done_callback(_observe)
        await asyncio.wait((self._shutdown,))
        self._shutdown.result()

    async def _close(self) -> None:
        try:
            initialization = self._initialization
            if initialization is not None:
                await asyncio.wait((initialization,))
                if not initialization.cancelled() and initialization.exception() is None:
                    await initialization.result().aclose()
        finally:
            retirement = self._retirement
            if retirement is not None:
                await asyncio.wait((retirement,))
                retirement.result()
