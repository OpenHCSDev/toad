"""Bounded page preparation for one immutable transcript snapshot."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import ClassVar, TYPE_CHECKING
from weakref import ReferenceType, ref

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import TranscriptEvent
from agent_comms.sent_message import OutgoingMessageReference

from toad.widgets.transcript_fragments import TranscriptFragment
from toad.widgets.transcript_fragments import transcript_fragments
from toad.render_backend import ReusableRenderTask
from toad.widgets.message_filter import MessageCategory
from toad.work_preparation import (
    PreparationRuntime,
    PreparedValue,
    PreparationScope,
    ReusableWork,
    ScopedWork,
    ThreadWork,
    WorkKey,
    WorkLane,
    retained_bytes,
)


if TYPE_CHECKING:
    from toad.widgets.conversation import Contents
    from toad.widgets.transcript_history import LineHistory


@dataclass
class PreparedTranscriptPage:
    """One transcript page's immutable fragments and the range a view draws."""

    BATCH: ClassVar[int] = 4

    page: TranscriptPage
    fragments: tuple[TranscriptFragment, ...]
    retained_bytes: int
    outgoing_coverage: frozenset[OutgoingMessageReference] = field(kw_only=True)
    fragment_range: tuple[int, int] | None = None

    @classmethod
    def prepare(cls, page: TranscriptPage) -> PreparedTranscriptPage:
        """Prepare and measure one whole page in the worker that owns its result."""
        fragments = transcript_fragments(page.events, resolve_sent=page.resolve_sent_messages)
        return cls.measured(page, fragments)

    @classmethod
    def measured(cls, page, fragments, **view):
        coverage = frozenset(reference for fragment in fragments
                             for reference in fragment.outgoing_sources)
        fragments = tuple(fragment.for_body_sources(coverage) for fragment in fragments)
        prepared = cls(page, fragments, 0, outgoing_coverage=coverage, **view)
        prepared.measure_sources()
        return prepared

    def measure_sources(self, readers=(), *, seen=None):
        self.retained_bytes = retained_bytes(
            (self.page, self.fragments, self.outgoing_coverage, *readers), seen=seen,
        )

    @classmethod
    def empty(cls, page):
        return cls.measured(page, ())

    def project(self, fragments):
        if len(fragments) == len(self.fragments) and all(
                selected is original for selected, original in zip(fragments, self.fragments)):
            return self.for_view()
        return type(self).measured(self.page, fragments)

    @staticmethod
    def initial_slice(fragments, batch_size: int, newest: bool) -> slice:
        start = max(0, len(fragments) - batch_size) if newest else 0
        return slice(start, min(len(fragments), start + batch_size))

    def can_extend(self, older: bool) -> bool:
        """Whether this already-decoded page has an unadmitted local range."""
        return self.start > 0 if older else self.stop < len(self.fragments)

    def configure(self, *, batch_size, newest=True):
        if self.fragment_range is None:
            self.set_fragment_range(self.initial_slice(self.fragments, batch_size, newest))

    async def prepare_rows(self, view: LineHistory, current: Callable[[], bool], *,
                           target: LineHistory | Contents, selected: frozenset[type[MessageCategory]],
                           boundary: int, older: bool, rows_needed: int, limit: int) -> int:
        """Select one directional range from its actual rendered rows.

        Latest destinations and ordinary edge travel use the same selection.
        This is a staged page: its range cannot change the mounted reader until
        the source owner publishes it under its original fences.
        """
        take = rows = 0
        available = boundary if older else len(self.fragments) - boundary
        while take < min(available, limit) and rows < rows_needed:
            count = min(view.budget.batch_items, limit - take, available - take)
            start = boundary - take - count if older else boundary + take
            batch = self.fragments[start:start + count]
            await view.prepare_fragments(batch, current, target=target, selected=selected)
            if not current():
                return 0
            for fragment in reversed(batch) if older else batch:
                lines = (fragment.lines_for(target.line_width, view.app.colours.line_theme)
                         if fragment.shown_in(selected) else None)
                take += 1
                rows += 0 if lines is None else lines.height
                if rows >= rows_needed:
                    break
        self.set_fragment_range(slice(boundary - take, boundary) if older
                                else slice(boundary, boundary + take))
        return rows

    @property
    def start(self):
        return self.fragment_range[0]

    @start.setter
    def start(self, start):
        self.fragment_range = start, self.fragment_range[1] if self.fragment_range is not None else start

    @property
    def stop(self):
        return self.fragment_range[1]

    @stop.setter
    def stop(self, stop):
        self.fragment_range = self.start, stop

    def set_fragment_range(self, selected: slice) -> None:
        self.fragment_range = selected.start, selected.stop

    def capture_range(self) -> PageFragmentRange:
        return PageFragmentRange(ref(self), self.start, self.stop, self.fragments[self.start:self.stop])

    def restore_range(self, fragment_range: PageFragmentRange) -> None:
        if fragment_range.page() is not self:
            return
        if len(fragment_range.members) != fragment_range.stop - fragment_range.start:
            raise RuntimeError("Original transcript suppliers do not cover their admission")
        self.set_fragment_range(slice(fragment_range.start, fragment_range.stop))

    @property
    def retained_source_bytes(self):
        return self.retained_bytes

    # A page draws its admitted fragments as lines: admission moves a range,
    # it never mounts or removes native members.
    async def extend(self, view, prepared: PreparedTranscriptPage, current) -> bool:
        """Admit the staged rows; the range owner alone combines its membership."""
        if not current():
            return False
        if prepared.fragments is not self.fragments:
            raise ValueError("Transcript input replacement requires a new prepared page")
        selected = slice(min(self.start, prepared.start), max(self.stop, prepared.stop))
        return await self.replace_range(view, selected, current)

    async def replace_range(self, view, selected, current) -> bool:
        if not current():
            return False
        self.set_fragment_range(selected)
        view.range_changed()
        return True

    def trim(self, view, count: int, *, older: bool) -> None:
        if older:
            self.start += count
        else:
            self.stop -= count
        view.range_changed()

    def for_view(self) -> PreparedTranscriptPage:
        """An independent view owns admission and resolved source acquisitions.

        The worker's immutable source/syntax remains reusable. Its stored page
        never acquires a frontend document or another projection's lifetime.
        """
        return replace(self, fragment_range=None)


@dataclass(frozen=True, eq=False)
class PageFragmentRange:
    """Reading demand holds this actual page's bounded source acquisitions.

    Reader intent retains its bounded original members, never the whole page.
    Native admission can move independently of these original source slots.
    Another page or projection never owns them merely because its backend
    interval happens to be equal.
    """

    page: ReferenceType[PreparedTranscriptPage] = field(repr=False)
    start: int
    stop: int
    members: tuple[TranscriptFragment, ...] = field(repr=False)

    def __eq__(self, other):
        if not isinstance(other, PageFragmentRange):
            return NotImplemented
        return ((page := self.page()) is not None and page is other.page()
                and self.start == other.start and self.stop == other.stop)


@dataclass(frozen=True)
class PageRequest:
    before: TranscriptCursor | None = None
    after: TranscriptCursor | None = None

    @classmethod
    def adjacent(cls, page: TranscriptPage, older: bool) -> PageRequest:
        return cls(before=page.before) if older else cls(after=page.after)


@dataclass(frozen=True)
class FilteredTranscriptBatch:
    prepared: PreparedTranscriptPage
    stop: int


@dataclass(frozen=True)
class TranscriptFilterWork(ThreadWork[FilteredTranscriptBatch]):
    """Select the next bounded presentation batch off-loop from source data."""

    page: PreparedTranscriptPage
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
            return FilteredTranscriptBatch(self.page.project(()), 0)
        while stop and len(matches) < self.limit:
            stop -= 1
            fragment = self.fragments[stop]
            if fragment.shown_in(self.selected):
                matches.append(fragment)
        return FilteredTranscriptBatch(self.page.project(tuple(reversed(matches))), stop)


class PreparedPageSource(ABC):
    """One lifetime-owned source of prepared pages, independent of widget paging."""

    runtime: PreparationRuntime
    scope: PreparationScope
    through: TranscriptCursor
    loader: Callable[..., Awaitable[TranscriptPage]] | None

    def __init__(self) -> None:
        # Custody moves here when native membership is revoked. These are the
        # original admitted resources, not another cache of transport pages.
        self.held_pages: tuple[PreparedTranscriptPage, ...] = ()
        self.projection_source: ProjectedTranscriptSource | None = None

    @property
    def retained_source_bytes(self) -> int:
        return sum(page.retained_bytes for page in self.held_pages) + (
            self.projection_source.retained_source_bytes if self.projection_source is not None else 0
        )

    def measure_held(self, pages: tuple[PreparedTranscriptPage, ...],
                          projection: ProjectedTranscriptSource | None = None,
                          ranges: tuple[PageFragmentRange, ...] = (),
                          *, seen: set[int] | None = None) -> None:
        """Partition retained source custody in the existing preparation worker.

        A tool's mutable acquisition need not be a field of its immutable
        dataclass input. Include each owner's declared suppliers, rather than
        assuming a graph walk of transport fields reaches every document.
        Canonical and projected pages share immutable inputs; their independent
        acquisitions remain distinct while this one traversal counts sharing.
        """
        if seen is None:
            seen = set()
        for page in pages:
            readers = tuple(page_range.members for page_range in ranges if page_range.page() is page)
            page.measure_sources(readers, seen=seen)
        if projection is not None:
            projection.measure_held(projection.held_pages, projection.projection_source,
                                         ranges, seen=seen)

    def park(self, pages: tuple[PreparedTranscriptPage, ...],
             projection: ProjectedTranscriptSource | None = None) -> None:
        if self.closed:
            raise ValueError("Cannot retain a revoked transcript source")
        self.held_pages, self.projection_source = pages, projection

    def release_held(self) -> None:
        """Native acquisition takes these same resources, not materialized copies."""
        self.held_pages, self.projection_source = (), None

    @property
    def closed(self) -> bool:
        return self.scope.closed

    @abstractmethod
    async def get(self, request: PageRequest) -> PreparedTranscriptPage:
        pass

    @abstractmethod
    async def prepare(self, request: PageRequest) -> None:
        """Prepare the original runtime resource without delivering another copy."""

    async def prepare_next(self, page: TranscriptPage, older: bool) -> None:
        if not self.closed and (page.has_older if older else page.has_newer):
            await self.prepare(PageRequest.adjacent(page, older))

    def close(self) -> None:
        self.runtime.discard_scope(self.scope)
        if self.projection_source is not None:
            self.projection_source.close()
        self.release_held()


class TranscriptPageProjection(ABC):
    @abstractmethod
    async def project(self, page: PreparedTranscriptPage, runtime: PreparationRuntime) -> PreparedTranscriptPage:
        pass


@dataclass(frozen=True)
class CategoryProjection(TranscriptPageProjection):
    selected: frozenset[type[MessageCategory]]

    def fragments_for(self, page):
        return page.fragments

    async def project(self, page: PreparedTranscriptPage, runtime: PreparationRuntime) -> PreparedTranscriptPage:
        # Project one source page on the model lane. Widget admission is owned
        # separately by the same bounded pager used for unfiltered history.
        fragments = self.fragments_for(page)
        matches = await runtime.submit(TranscriptFilterWork(
            page, fragments, self.selected, len(fragments), len(fragments),
        ))
        return matches.prepared


@dataclass(frozen=True)
class RangeCategoryProjection(CategoryProjection):
    boundary: PageFragmentRange

    def fragments_for(self, page):
        if self.boundary.page() is page:
            return self.boundary.members
        return super().fragments_for(page)


@dataclass(frozen=True)
class TranscriptPageRenderTask(ReusableRenderTask[PreparedTranscriptPage]):
    page: TranscriptPage

    def execute(self) -> PreparedTranscriptPage:
        return PreparedTranscriptPage.prepare(self.page)

    def accept_result(self, result: object) -> PreparedTranscriptPage:
        if not isinstance(result, PreparedTranscriptPage):
            raise TypeError("Transcript renderer returned an invalid page")
        return result


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

    async def execute(
        self, runtime: PreparationRuntime, key: WorkKey,
    ) -> tuple[PreparedValue[PreparedTranscriptPage], int]:
        request = self.request
        page = await self.loader(before=request.before, after=request.after, through=self.through)
        cursor = request.before or request.after
        if cursor is not None:
            edge = page.before if request.before is not None else page.after
            more = page.has_older if request.before is not None else page.has_newer
            wrong_direction = (edge.contains(cursor) if request.before is not None
                               else cursor.contains(edge))
            if edge.session_file != cursor.session_file or (wrong_direction and more):
                raise ValueError("Transcript history made no cursor progress")
        if self.scope.closed:
            raise asyncio.CancelledError
        prepared = await runtime.renderer.capture(TranscriptPageRenderTask(page))
        return await runtime.run_thread(self.finish_prepared, key, prepared)


class TranscriptPageBuffer(PreparedPageSource):
    """Prepared pages for a snapshot; storage and work limits belong to the runtime.

    The loader retains ownership of transcript/routing semantics and off-loop
    I/O. CPU preparation uses the application's existing renderer. Foreground
    consumers share in-flight requests; cancelling one waiter cannot release a
    still-running read's admission or publish it into a closed view.
    """

    # The work that reads and prepares one page of this kind of source.
    work: ClassVar[type[TranscriptPageWork]] = TranscriptPageWork

    def __init__(
        self, loader: Callable[..., Awaitable[TranscriptPage]] | None, through: TranscriptCursor,
        runtime: PreparationRuntime,
    ) -> None:
        super().__init__()
        self.loader, self.through, self.runtime = loader, through, runtime
        self.scope = PreparationScope()

    @property
    def closed(self) -> bool:
        return self.scope.closed

    async def get(self, request: PageRequest) -> PreparedTranscriptPage:
        if self.loader is None:
            raise ValueError("This transcript has no saved-source reader")
        result = await self.runtime.submit(self.work(self.scope, self.loader, self.through, request))
        return result.for_view()

    async def prepare(self, request: PageRequest) -> None:
        if self.loader is not None:
            await self.runtime.prepare(self.work(self.scope, self.loader, self.through, request))

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
        super().__init__()
        self.loader, self.runtime, self.projection = loader, runtime, projection
        self._upstream = upstream
        self.through = boundary.page.after
        self._raw = TranscriptPageBuffer(loader, boundary.page.before, runtime) if loader is not None else None
        self.scope = self._raw.scope if self._raw is not None else PreparationScope()
        self._boundary = boundary
        self._projected_boundary: PreparedTranscriptPage | None = None

    async def _project(self, prepared: PreparedTranscriptPage) -> PreparedTranscriptPage:
        """Publish this source's projection only inside its original lifetime."""
        if self.closed:
            raise asyncio.CancelledError
        projected = await self.projection.project(prepared, self.runtime)
        if self.closed:
            raise asyncio.CancelledError
        return projected

    async def boundary(self) -> PreparedTranscriptPage:
        if self.closed:
            raise asyncio.CancelledError
        if self._projected_boundary is None:
            projected = await self._project(self._boundary)
            self._projected_boundary = replace(projected, page=replace(
                projected.page, has_newer=False,
                has_older=projected.page.has_older and self.loader is not None,
            ))
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
        prepared = await self._project(initial)
        if not older and not prepared.fragments and not prepared.page.has_newer:
            boundary = await self.boundary()
            return replace(boundary, page=replace(
                boundary.page, before=initial.page.before,
                has_older=initial.page.has_older,
            ))
        # One requested source page, including an empty matching interval.
        # Only the viewport or an explicit filter scan may request another;
        # a projection cannot decode arbitrary older pages behind that request.
        return replace(prepared, page=replace(prepared.page, has_newer=True))

    async def prepare(self, request: PageRequest) -> None:
        if self.closed:
            return
        if (request.before == self.through
                or request.after == self._boundary.page.before or self._raw is None):
            await self.boundary()
            return
        reader = (self._upstream if request.before is not None
                  and self._upstream is not None and not self._upstream.closed else self._raw)
        await reader.prepare(request)

    def close(self) -> None:
        super().close()
        if self._raw is not None:
            self._raw.close()
        self._projected_boundary = None
        self._upstream = None
        self._raw = None
        self.loader = None
