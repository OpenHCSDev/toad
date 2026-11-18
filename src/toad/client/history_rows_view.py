"""Two toolkit-neutral answers to `BoundViewHost`, for a view that needs them.

`HistoryRowsBlocks`: a view that draws every transcript block as rows of its one history
model. It never stands live blocks, so nothing retires or is protected, every refresh
commits, and no chronological entry splits the history.

`AsyncioPublications`: a view whose publications run as tasks on its asyncio loop, which
applies a queued callback before running the next. The view supplies `call_later`.
Qt's thread views inherit both; Textual's `Conversation` answers with its widgets and
workers instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from functools import cached_property
from typing import ClassVar

from toad.transcript_publication import TaskPublicationWork


async def settled() -> None:
    """An awaitable for a native change applied at once."""


class HistoryRowsBlocks:
    MAX_LIVE_BLOCKS: ClassVar[int] = 1
    """No live blocks stand, so every refresh commits into the history."""

    @property
    def live_blocks(self) -> tuple[object, ...]:
        return (self.transcript_history,)

    def retire_blocks(self, blocks: Sequence[object]) -> Awaitable[None]:
        if blocks:
            raise ValueError(f"A history-rows view draws no live blocks to retire: {blocks!r}")
        return settled()

    def protected_blocks(self, candidates: Iterable[object]) -> set[object]:
        return set()

    def blocks_in_viewport(self, candidates: Sequence[object]) -> bool:
        return False

    def later_history(self, page, source, conversation_order: int):
        raise ValueError("A history-rows view posts no chronological live entries, so its history never splits")


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
