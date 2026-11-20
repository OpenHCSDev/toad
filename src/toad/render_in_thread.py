"""In-process renderer for platforms that do not host child processes.

Android's Python has no ``_multiprocessing``, so ``RenderProcessPool`` cannot
run there. This renderer executes each ``RenderTask`` in a worker thread on the
owning event loop, preserving the same ``Renderer`` contract (``capture``,
``submit``, ``aclose``) the rest of the app depends on.
"""

from __future__ import annotations

import asyncio
from typing import TypeVar

from toad.render_backend import Renderer, RenderTask
from toad.work_preparation import PreparedValue

Result = TypeVar("Result")


class InThreadRenderer(Renderer):
    """Run render tasks in-thread on the owning loop; no child processes."""

    needs_submission = False

    def __init__(self) -> None:
        super().__init__()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def start(self) -> None:
        """In-thread rendering needs no spawn preparation."""

    async def capture(self, task: RenderTask[Result]) -> PreparedValue[Result]:
        if self._closed:
            raise RuntimeError("InThreadRenderer is closed")
        return await task.complete_capture(asyncio.to_thread(task.capture_result))

    async def aclose(self) -> None:
        self._closed = True
        await self._close_submissions()
