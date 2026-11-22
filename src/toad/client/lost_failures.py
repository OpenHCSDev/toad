"""Failures of work nobody waits for."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine


class LostFailures:
    """Work started on an event loop that failed with nobody to tell.

    asyncio keeps a task's exception until something takes it, and says "never retrieved" only
    when the task is collected. A task something still holds is never collected, so its failure
    is never said: a conversation view whose construction raised simply never opened, with no
    error file, no log line and no notice (a property named like a Qt signal, 2026-11-21).

    Every task the loop makes is watched. One that ends in an exception nobody has taken, once
    every waiter it had has run, is shown at once, as any error is; so is what asyncio reports
    of its own (a callback that raised)."""

    def __init__(self, show: Callable[[BaseException | str, str], None]) -> None:
        self.show = show

    def hear(self, loop: asyncio.AbstractEventLoop) -> None:
        loop.set_task_factory(self.task)
        loop.set_exception_handler(self.reported)

    def task(self, loop: asyncio.AbstractEventLoop, work: Coroutine, **options) -> asyncio.Task:
        made = asyncio.Task(work, loop=loop, **options)
        made.add_done_callback(self.ended)
        return made

    def ended(self, task: asyncio.Task) -> None:
        """The task's waiters are told after this callback, which was added first: look again
        once they have run."""
        if not task.cancelled():
            task.get_loop().call_soon(self.untaken, task)

    def untaken(self, task: asyncio.Task) -> None:
        # asyncio's own mark of an exception nothing took: what it would log at collection.
        if task._log_traceback:
            self.show(task.exception(), f"{task.get_name()} failed")

    def reported(self, loop: asyncio.AbstractEventLoop, context: dict) -> None:
        """asyncio's own report: it is logged as before, and shown."""
        loop.default_exception_handler(context)
        failure = context.get("exception")
        self.show(context["message"] if failure is None else failure, context["message"])
