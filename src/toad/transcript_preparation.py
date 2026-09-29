"""Bounded, data-only lookahead for one immutable transcript snapshot."""

from __future__ import annotations

from toad.widgets.message_filter import InboundCategory

import asyncio
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import TranscriptEvent

from toad.widgets.transcript_fragments import TranscriptFragment
from toad.render_tasks import TranscriptRenderTask
from toad.widgets.message_filter import MessageCategory, event_category, keep_events
from toad.work_preparation import (
    PreparationRuntime,
    RenderPreparation,
    PreparationScope,
    SerializedWork,
    ScopedWork,
    ThreadWork,
    WorkKey,
    WorkLane,
    retained_bytes,
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


def incoming_sequences(events: tuple[TranscriptEvent, ...]) -> frozenset[int]:
    return frozenset(
        event.routing.requests[0].seq
        for event in events
        if event_category(event) is InboundCategory
        and event.routing is not None
        and event.routing.requests
        and event.routing.requests[0].seq > 0
    )


@dataclass(frozen=True)
class CommittedInterval:
    """Bounded, data-only coverage reads; never prepare or mount unread bodies."""

    before: TranscriptCursor
    through: TranscriptCursor

    async def coverage(self, loader, wanted: frozenset[int], runtime: PreparationRuntime,
                       is_current: Callable[[], bool]) -> frozenset[int] | None:
        if self.before.session_file != self.through.session_file or self.before.offset > self.through.offset:
            raise ValueError("Commit does not extend the retained source")
        found: set[int] = set()
        cursor = self.before
        while wanted - found and cursor.offset < self.through.offset:
            if not is_current():
                return None
            page = await loader(after=cursor, through=self.through)
            if not is_current():
                return None
            if (page.before.session_file != cursor.session_file
                    or page.after.session_file != cursor.session_file
                    or page.before.offset < cursor.offset
                    or not cursor.offset < page.after.offset <= self.through.offset):
                raise ValueError("Committed coverage made no valid cursor progress")
            sequences = await runtime.run_thread(incoming_sequences, page.events)
            found.update(sequences & wanted)
            cursor = page.after
        return frozenset(found) if is_current() else None


@dataclass(frozen=True)
class FilteredTranscriptBatch:
    fragments: tuple[TranscriptFragment, ...]
    stop: int


@dataclass(frozen=True)
class TranscriptFilterWork(ThreadWork[FilteredTranscriptBatch]):
    """Select the next bounded presentation batch off-loop from source data."""

    fragments: tuple[TranscriptFragment, ...]
    selected: frozenset[type[MessageCategory]]
    stop: int
    limit: int

    async def identity(self, runtime: PreparationRuntime) -> WorkKey:
        # This is a cursor operation, not a retained copy of the source history.
        return WorkKey(type(self), object())

    def prepare(self) -> FilteredTranscriptBatch:
        matches = []
        stop = self.stop
        if not self.selected:
            return FilteredTranscriptBatch((), 0)
        while stop and len(matches) < self.limit:
            stop -= 1
            fragment = self.fragments[stop]
            if keep_events(fragment.events, self.selected):
                matches.append(fragment)
        return FilteredTranscriptBatch(tuple(reversed(matches)), stop)


class PreparedPageSource(ABC):
    """One lifetime-owned source of prepared pages, independent of widget paging."""

    runtime: PreparationRuntime
    scope: PreparationScope
    through: TranscriptCursor
    loader: Callable[..., Awaitable[TranscriptPage]] | None

    @property
    def closed(self) -> bool:
        return self.scope.closed

    @abstractmethod
    async def get(self, request: PageRequest) -> PreparedTranscriptPage:
        pass

    @abstractmethod
    async def prefetch(
        self, before: TranscriptCursor | None, after: TranscriptCursor | None,
        keep_going: Callable[[], bool], *, rounds: int = 1,
    ) -> bool:
        pass

    @abstractmethod
    def close(self) -> None:
        pass


class TranscriptPageProjection(ABC):
    @abstractmethod
    async def project(self, page: PreparedTranscriptPage, runtime: PreparationRuntime) -> PreparedTranscriptPage:
        pass


@dataclass(frozen=True)
class CategoryProjection(TranscriptPageProjection):
    selected: frozenset[type[MessageCategory]]

    async def project(self, page: PreparedTranscriptPage, runtime: PreparationRuntime) -> PreparedTranscriptPage:
        # Project one source page on the model lane. Widget admission is owned
        # separately by the same bounded pager used for unfiltered history.
        matches = await runtime.submit(TranscriptFilterWork(
            page.fragments, self.selected, len(page.fragments), len(page.fragments),
        ))
        return replace(page, fragments=matches.fragments)


@dataclass(frozen=True)
class TranscriptPageWork(SerializedWork[PreparedTranscriptPage], ScopedWork[PreparedTranscriptPage]):
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
        fragments = await runtime.submit(RenderPreparation(TranscriptRenderTask(page.events)))
        size = await runtime.run_thread(retained_bytes, (page, fragments))
        return PreparedTranscriptPage(page, fragments, size)


class TranscriptPageBuffer(PreparedPageSource):
    """Lookahead intent for a snapshot; storage/admission belong to the runtime.

    The loader retains ownership of transcript/routing semantics and off-loop
    I/O. CPU preparation uses the application's existing renderer. Foreground
    consumers share in-flight requests; cancelling one waiter cannot release a
    still-running read's admission or publish it into a closed view.
    """

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
        keep_going: Callable[[], bool], *, rounds: int = 1,
    ) -> bool:
        """Warm both edges fairly; stop hidden/closed work and failed read loops."""
        for _ in range(min(rounds, self.runtime.max_entries)):
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
                    if len(self._blocked) > self.runtime.max_entries:
                        self._blocked.popitem(last=False)
                    prepared = None
                if older:
                    before = (prepared.page.before if prepared is not None
                              and prepared.page.has_older and prepared.retained_bytes <= self.runtime.max_bytes
                              else None)
                else:
                    after = (prepared.page.after if prepared is not None
                             and prepared.page.has_newer and prepared.retained_bytes <= self.runtime.max_bytes
                             else None)
            if before is None and after is None:
                break
        return True


class ProjectedTranscriptSource(PreparedPageSource):
    """A projected prefix with a fixed boundary and ordinary bidirectional reads.

    The boundary is the unadmitted prefix of one canonical page. Earlier reads
    stop at its native before cursor; reaching that cursor forwards returns the
    retained boundary rather than overlapping the canonical mounted tail.
    Only the boundary and the caller's bounded pages remain strongly retained.
    """

    def __init__(
        self, boundary: PreparedTranscriptPage,
        loader: Callable[..., Awaitable[TranscriptPage]] | None,
        runtime: PreparationRuntime, projection: TranscriptPageProjection,
        upstream: PreparedPageSource | None = None,
    ) -> None:
        self.loader, self.runtime, self.projection = loader, runtime, projection
        self._upstream = upstream
        self.through = boundary.page.after
        self._raw = TranscriptPageBuffer(loader, boundary.page.before, runtime) if loader is not None else None
        self.scope = self._raw.scope if self._raw is not None else PreparationScope()
        self._boundary = replace(boundary, page=replace(
            boundary.page, has_newer=False,
            has_older=boundary.page.has_older and loader is not None,
        ))
        self._projected_boundary: PreparedTranscriptPage | None = None

    async def boundary(self) -> PreparedTranscriptPage:
        if self.closed:
            raise asyncio.CancelledError
        if self._projected_boundary is None:
            projected = await self.projection.project(self._boundary, self.runtime)
            if self.closed:
                raise asyncio.CancelledError
            self._projected_boundary = projected
        return self._projected_boundary

    async def get(self, request: PageRequest) -> PreparedTranscriptPage:
        if self.closed:
            raise asyncio.CancelledError
        if (request.before == self.through
                or request.after == self._boundary.page.before or self._raw is None):
            return await self.boundary()
        older = request.before is not None
        reader = (self._upstream if older and self._upstream is not None and not self._upstream.closed
                  else self._raw)
        initial = await reader.get(request)
        prepared = initial
        while True:
            if self.closed:
                raise asyncio.CancelledError
            prepared = await self.projection.project(prepared, self.runtime)
            if self.closed:
                raise asyncio.CancelledError
            if prepared.fragments:
                break
            more = prepared.page.has_older if older else prepared.page.has_newer
            if not more:
                if not older:
                    boundary = await self.boundary()
                    return replace(boundary, page=replace(
                        boundary.page, before=initial.page.before,
                        has_older=initial.page.has_older,
                    ))
                break
            prepared = await reader.get(PageRequest(
                before=prepared.page.before if older else None,
                after=prepared.page.after if not older else None,
            ))
        # Unmatched intervals advance source cursors, not empty widget pages.
        # Retain the whole scanned span so reversing direction cannot skip a
        # matching record or repeatedly rediscover an empty interval.
        page = replace(
            prepared.page,
            before=prepared.page.before if older else initial.page.before,
            after=initial.page.after if older else prepared.page.after,
            has_older=prepared.page.has_older if older else initial.page.has_older,
            has_newer=True,
        )
        return replace(prepared, page=page)

    async def prefetch(
        self, before: TranscriptCursor | None, after: TranscriptCursor | None,
        keep_going: Callable[[], bool], *, rounds: int = 1,
    ) -> bool:
        if self.closed or not keep_going():
            return False
        if self._raw is None:
            return True
        limit = self._boundary.page.before.offset
        if self._upstream is not None and not self._upstream.closed:
            await self._upstream.prefetch(
                before if before is not None and before.offset <= limit else None,
                None, keep_going, rounds=rounds,
            )
            before = None
        if self.closed:
            return False
        assert self._raw is not None
        return await self._raw.prefetch(
            before if before is not None and before.offset <= limit else None,
            after if after is not None and after.offset < limit else None,
            keep_going, rounds=rounds,
        )

    def close(self) -> None:
        if self._raw is not None:
            self._raw.close()
        else:
            self.runtime.discard_scope(self.scope)
        self._projected_boundary = None
        self._upstream = None
        self._raw = None
        self.loader = None
