"""Bounded, data-only lookahead for one immutable transcript snapshot."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agent_comms import TranscriptCursor, TranscriptPage

from toad.widgets.transcript_fragments import TranscriptFragment, prepare_transcript_fragments
from toad.work_preparation import (
    PreparationRuntime, PreparationScope, ReusableWork, ScopedWork, WorkKey, WorkLane, retained_bytes,
)


@dataclass(frozen=True)
class PreparedTranscriptPage:
    page: TranscriptPage
    fragments: tuple[TranscriptFragment, ...]
    retained_bytes: int


@dataclass(frozen=True)
class PageRequest:
    before: TranscriptCursor | None = None
    after: TranscriptCursor | None = None


@dataclass(frozen=True)
class TranscriptPageWork(ReusableWork[PreparedTranscriptPage], ScopedWork[PreparedTranscriptPage]):
    scope: PreparationScope
    loader: Callable[..., Awaitable[TranscriptPage]]
    through: TranscriptCursor
    request: PageRequest
    lane = WorkLane.MODEL

    @property
    def work_key(self) -> WorkKey:
        return WorkKey(type(self), (self.through, self.request), self.scope)

    def result_size(self, result: PreparedTranscriptPage) -> int:
        return result.retained_bytes

    async def execute(self, runtime: PreparationRuntime) -> PreparedTranscriptPage:
        request = self.request
        page = await self.loader(before=request.before, after=request.after, through=self.through)
        cursor = request.before or request.after
        if cursor is not None:
            edge = page.before if request.before is not None else page.after
            more = page.has_older if request.before is not None else page.has_newer
            wrong_direction = (edge.offset >= cursor.offset if request.before is not None
                               else edge.offset <= cursor.offset)
            if edge.session_file != cursor.session_file or (wrong_direction and more):
                raise ValueError("Transcript history made no cursor progress")
        if self.scope.closed:
            raise asyncio.CancelledError
        fragments = await prepare_transcript_fragments(page.events, runtime.renderer, background=True)
        size = await runtime.run_thread(retained_bytes, (page, fragments))
        return PreparedTranscriptPage(page, fragments, size)


class TranscriptPageBuffer:
    """Lookahead intent for a snapshot; storage/admission belong to the runtime.

    The loader retains ownership of transcript/routing semantics and off-loop
    I/O. CPU preparation uses the application's existing renderer. Foreground
    consumers share in-flight requests; cancelling one waiter cannot release a
    still-running read's admission or publish it into a closed view.
    """

    LOOKAHEAD = 8
    MAX_BYTES = 4 * 1024 * 1024

    def __init__(
        self, loader: Callable[..., Awaitable[TranscriptPage]], through: TranscriptCursor,
        runtime: PreparationRuntime,
    ) -> None:
        self.loader, self.through, self.runtime = loader, through, runtime
        self.scope = PreparationScope()
        self._blocked: OrderedDict[PageRequest, None] = OrderedDict()

    @property
    def closed(self) -> bool:
        return self.scope.closed

    def close(self) -> None:
        self.runtime.discard_scope(self.scope)
        self._blocked.clear()

    async def get(self, request: PageRequest) -> PreparedTranscriptPage:
        result = await self.runtime.submit(TranscriptPageWork(self.scope, self.loader, self.through, request))
        self._blocked.pop(request, None)
        return result

    async def prefetch(
        self, before: TranscriptCursor | None, after: TranscriptCursor | None,
        keep_going: Callable[[], bool],
    ) -> bool:
        """Warm both edges fairly; stop hidden/closed work and failed read loops."""
        for _ in range(self.LOOKAHEAD):
            for older in (True, False):
                cursor = before if older else after
                if cursor is None:
                    continue
                if self.closed or not keep_going():
                    return False
                request = PageRequest(before=cursor) if older else PageRequest(after=cursor)
                if request in self._blocked:
                    if older:
                        before = None
                    else:
                        after = None
                    continue
                try:
                    prepared = await self.get(request)
                except (OSError, ValueError):
                    # A foreground request can retry/report the error. Repeated
                    # layout signals must not keep retrying speculative failures.
                    self._blocked[request] = None
                    if len(self._blocked) > self.LOOKAHEAD * 2:
                        self._blocked.popitem(last=False)
                    prepared = None
                if older:
                    before = (prepared.page.before if prepared is not None
                              and prepared.page.has_older and prepared.retained_bytes <= self.MAX_BYTES
                              else None)
                else:
                    after = (prepared.page.after if prepared is not None
                             and prepared.page.has_newer and prepared.retained_bytes <= self.MAX_BYTES
                             else None)
            if before is None and after is None:
                break
        return True
