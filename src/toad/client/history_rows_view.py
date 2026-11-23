"""Toolkit-neutral asyncio publication runner for `BoundViewHost`.

`AsyncioPublications`: a view whose publications run as tasks on its asyncio loop, which
applies a queued callback before running the next. The view supplies `call_later`.
Qt's views inherit it; Textual's `Conversation` answers with its widgets and workers instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import cached_property, partial

from toad.transcript_publication import TaskPublicationWork


async def settled() -> None:
    """An awaitable for a native change applied at once."""


class AsyncioPublications:
    @cached_property
    def _publications(self) -> set[TaskPublicationWork]:
        return set()

    def on_native_pump(self) -> bool:
        return False

    async def native_applied(self) -> bool:
        applied = asyncio.get_running_loop().create_future()
        if not self.call_later(lambda: applied.done() or applied.set_result(None)):
            return False
        await applied
        return self.is_attached

    def start_publication(self, task: Callable[[], Awaitable[object]], *, exclusive: bool) -> TaskPublicationWork:
        if exclusive:
            for running in tuple(self._publications):
                if running.exclusive:
                    running.cancel()
        work = TaskPublicationWork(asyncio.ensure_future(task()), exclusive)
        self._publications.add(work)
        work.task.add_done_callback(lambda _task: self._publications.discard(work))
        return work

    def cancel_publications(self) -> tuple[TaskPublicationWork, ...]:
        running = tuple(self._publications)
        for work in running:
            work.cancel()
        return running

    def current_publication(self) -> object:
        return asyncio.current_task()

    def join_completion(self, completion: object) -> None:
        task = asyncio.ensure_future(completion())
        task.add_done_callback(self._completion_done)

    def _completion_done(self, task: asyncio.Task) -> None:
        if not task.cancelled() and self.is_attached and (error := task.exception()) is not None:
            self.app.show_error(error, "Transcript coverage failed")

    @cached_property
    def _workers(self) -> dict[str, asyncio.Task]:
        return {}

    def run_worker(self, work: Callable[[], Awaitable[object]], *, group: str, exclusive: bool = False) -> asyncio.Task:
        """Textual's `run_worker` on the asyncio loop: an exclusive worker cancels the one
        running in its group."""
        if exclusive and (running := self._workers.get(group)) is not None:
            running.cancel()
        task = asyncio.ensure_future(work())
        self._workers[group] = task
        task.add_done_callback(partial(self.worker_finished, group))
        return task

    def worker_finished(self, group: str, task: asyncio.Task) -> None:
        """A failed worker is shown and saved, as a failed Textual worker ends that app with
        its traceback; the task is no longer held, so nothing keeps its error unread."""
        if self._workers.get(group) is task:
            del self._workers[group]
        if not task.cancelled() and (error := task.exception()) is not None:
            self.app.show_error(error, f"{group.capitalize()} failed")
