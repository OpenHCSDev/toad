"""Bounded page preparation for one immutable transcript snapshot."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from itertools import islice
from dataclasses import dataclass, field, replace
from typing import ClassVar, TYPE_CHECKING
from weakref import ReferenceType, ref

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import TranscriptEvent
from agent_comms.sent_message import OutgoingMessageReference

from toad.widgets.presentation_window import OLDER_END, PageEnd, PageRequest
from toad.transcript_state import LatestViewportRequest
from toad.widgets.history_anchor import LatestPosition
from toad.widgets.message_notifications import NothingToRead, PaintedRead
from toad.widgets.transcript_fragments import TranscriptFragment
from toad.widgets.transcript_fragments import transcript_fragments
from toad.render_backend import ReusableRenderTask
from agent_comms.ui_model.message_category import MessageCategory
from toad.work_preparation import (
    PreparationRuntime,
    PreparedResult,
    PreparationScope,
    ReusableWork,
    ScopedWork,
    ThreadWork,
    WorkKey,
    WorkLane,
    WorkRevision,
    UniqueRevision,
)


if TYPE_CHECKING:
    from toad.widgets.conversation import Contents
    from toad.widgets.transcript_history import LineHistory


@dataclass
class PreparedTranscriptPage:
    """One transcript page's immutable fragments and the range a view draws."""

    page: TranscriptPage
    fragments: tuple[TranscriptFragment, ...]
    retained_bytes: int
    outgoing_coverage: frozenset[OutgoingMessageReference] = field(kw_only=True)
    fragment_range: tuple[int, int] | None = None

    def __deepcopy__(self, memo):
        """Copy page-local fields; keep the original source and fragments."""
        return replace(self)

    @classmethod
    def prepare(cls, page: TranscriptPage) -> PreparedTranscriptPage:
        """Prepare and measure one whole page in the worker that owns its result."""
        fragments = transcript_fragments(page.events, resolve_sent=page.resolve_sent_messages)
        return cls.measured(page, fragments)

    @classmethod
    def measured(cls, page, fragments, **view):
        coverage = frozenset(reference for fragment in fragments
                             for reference in fragment.outgoing_sources)
        prepared = cls(page, fragments, 0, outgoing_coverage=coverage, **view)
        prepared.measure_sources()
        return prepared

    @property
    def source_payload_bytes(self) -> int:
        return sum(256 + 4 * event.text_size for event in self.page.events)

    def measure_sources(self):
        """The page owns its events; each fragment owns only its acquired rows."""
        self.retained_bytes = (256 + 64 * len(self.outgoing_coverage)
                               + self.source_payload_bytes
                               + sum(fragment.retained_bytes for fragment in self.fragments))

    @classmethod
    def empty(cls, page):
        return cls.measured(page, ())

    def project(self, fragments):
        if len(fragments) == len(self.fragments) and all(
                selected is original for selected, original in zip(fragments, self.fragments)):
            return self.for_view()
        return type(self).measured(self.page, fragments)

    def configure(self, *, batch_size):
        if self.fragment_range is None:
            self.set_fragment_range(slice(max(0, len(self.fragments) - batch_size), len(self.fragments)))

    @property
    def fragments_in_range(self):
        return self.fragments[self.start:self.stop]

    async def prepare_rows(self, view: LineHistory, current: Callable[[], bool], *,
                           target: LineHistory | Contents, selected: frozenset[type[MessageCategory]],
                           boundary: int, end: PageEnd, rows_needed: int, limit: int) -> int:
        """Select one directional range from its actual rendered rows.

        Latest destinations and ordinary edge travel use the same selection.
        This is a staged page: its range cannot change the mounted reader until
        the source owner publishes it under its original fences.
        """
        take = rows = 0
        start = stop = boundary
        indices = iter(end.indices(self, boundary))
        while take < limit and rows < rows_needed:
            batch = tuple(islice(indices, min(view.budget.batch_items, limit - take)))
            if not batch:
                break
            await view.prepare_fragments(tuple(self.fragments[index] for index in batch),
                                         current, target=target, selected=selected)
            if not current():
                return 0
            for index in batch:
                fragment = self.fragments[index]
                lines = (fragment.lines_for(target.line_width, view.app.colours.line_theme)
                         if fragment.shown_in(selected) else None)
                take += 1
                start, stop = min(start, index), max(stop, index + 1)
                rows += 0 if lines is None else lines.height
                if rows >= rows_needed:
                    break
        self.set_fragment_range(slice(start, stop))
        return rows

    @property
    def start(self):
        return self.fragment_range[0]

    @property
    def stop(self):
        return self.fragment_range[1]

    def set_fragment_range(self, selected: slice) -> None:
        self.fragment_range = selected.start, selected.stop

    def capture_range(self) -> PageFragmentRange:
        return PageFragmentRange(ref(self), self.start, self.stop, self.fragments[self.start:self.stop])

    def restore_range(self, fragment_range: PageFragmentRange) -> None:
        if fragment_range.page() is not self:
            return
        if len(fragment_range.members) != fragment_range.stop - fragment_range.start:
            raise RuntimeError("Original transcript suppliers do not cover their range")
        self.set_fragment_range(slice(fragment_range.start, fragment_range.stop))

    # A page draws its selected fragments as lines: drawing moves a range,
    # it never mounts or removes native members.
    async def extend(self, view, prepared: PreparedTranscriptPage, current) -> bool:
        """Accept the staged rows; the range owner alone combines its membership."""
        if not current():
            return False
        if prepared.fragments is not self.fragments:
            raise ValueError("Transcript input replacement requires a new prepared page")
        selected = slice(min(self.start, prepared.start), max(self.stop, prepared.stop))
        return await self.replace_range(view, selected, current)

    async def replace_range(self, view, selected, current) -> bool:
        if not current():
            return False
        if self.fragment_range != (selected.start, selected.stop):
            self.set_fragment_range(selected)
            view.range_changed()
        return True

    def same_source(self, other: PreparedTranscriptPage) -> bool:
        """Keep a view only when its bounded read came from the same source snapshot."""
        # A filtered page can share the Core read but draw different members.
        # The retained worker result shares this immutable tuple with its views;
        # another projection cannot borrow that view's prepared rows. Each page
        # type owns equality of its source, traversal and read evidence.
        return self.fragments is other.fragments and self.page == other.page

    def for_view(self) -> PreparedTranscriptPage:
        """An independent view owns its drawing range and loaded source data.

        The worker's immutable source/syntax remains reusable. Its stored page
        never acquires a frontend document or another projection's lifetime.
        """
        return replace(self, fragment_range=None)


@dataclass(frozen=True, eq=False)
class PageFragmentRange:
    """Reading demand holds this actual page's bounded source acquisitions.

    Reader intent retains its bounded original members, never the whole page.
    The drawn range can move independently of these source slots.
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
class PageRevision[Cursor = TranscriptCursor | None](WorkRevision):
    through: Cursor | None
    request: PageRequest[Cursor]
    size: ClassVar[int] = 512


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
        # This is a cursor operation, not a kept copy of the source history.
        return WorkKey(type(self), UniqueRevision())

    def result_size(self, result: FilteredTranscriptBatch) -> int:
        return 64 + result.prepared.retained_bytes

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


class HeldProjection(ABC):
    """The parked projection's pages, accounting and lifetime."""

    held_pages: tuple[PreparedTranscriptPage, ...]

    @property
    @abstractmethod
    def retained_source_bytes(self) -> int: ...

    @abstractmethod
    def measure_projection(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class NoProjection(HeldProjection):
    held_pages = ()
    retained_source_bytes = 0

    def measure_projection(self) -> None:
        pass

    def close(self) -> None:
        pass


class PreparedPageSource(ABC):
    """One lifetime-owned source of prepared pages, independent of widget paging."""

    runtime: PreparationRuntime
    scope: PreparationScope
    through: TranscriptCursor

    def __init__(self) -> None:
        # This source holds the resources after their widgets detach. These are the
        # original accepted resources, not another cache of transport pages.
        self.held_pages: tuple[PreparedTranscriptPage, ...] = ()
        self.projection_source: HeldProjection = NoProjection()

    @property
    def retained_source_bytes(self) -> int:
        return sum(page.retained_bytes for page in self.held_pages) + self.projection_source.retained_source_bytes

    def measure_held(self, pages: tuple[PreparedTranscriptPage, ...],
                     projection: HeldProjection = NoProjection()) -> None:
        """Reader ranges reference these same fragments; charge them once."""
        for page in pages:
            page.measure_sources()
        projection.measure_projection()

    def park(self, pages: tuple[PreparedTranscriptPage, ...],
             projection: HeldProjection = NoProjection()) -> None:
        if self.closed:
            raise ValueError("Cannot retain a revoked transcript source")
        self.held_pages, self.projection_source = pages, projection

    def release_held(self) -> None:
        """Native acquisition takes these same resources, not materialized copies."""
        self.held_pages, self.projection_source = (), NoProjection()

    @property
    def closed(self) -> bool:
        return self.scope.closed

    async def get(self, request: PageRequest) -> PreparedTranscriptPage:
        if self.closed:
            raise asyncio.CancelledError
        prepared = await self._get(request)
        if self.closed:
            raise asyncio.CancelledError
        return prepared

    @abstractmethod
    async def _get(self, request: PageRequest) -> PreparedTranscriptPage: ...

    async def prepare(self, request: PageRequest) -> None:
        if not self.closed:
            await self._prepare(request)

    @abstractmethod
    async def _prepare(self, request: PageRequest) -> None: ...

    def reload_key(self):
        return self.scope

    def has_more(self, end: PageEnd, page: TranscriptPage) -> bool:
        return end.has_more(self.through, page)

    def has_older(self, page: TranscriptPage) -> bool:
        return page.has_older

    def edge_reached(self, request: PageRequest, boundary) -> bool:
        return request.cursor == boundary

    async def latest(self, prepared: PreparedTranscriptPage) -> PreparedTranscriptPage:
        if prepared.page.after == self.through:
            return prepared.for_view()
        return (await self.get(PageRequest(OLDER_END, self.through))).for_view()

    @abstractmethod
    def prefix(self, through) -> PreparedPageSource: ...

    async def prepare_next(self, page: TranscriptPage, end: PageEnd) -> None:
        if self.has_more(end, page):
            await self.prepare(end.adjacent(page))

    def restart(self, through) -> None:
        """Discard the old reading without discarding its storage binding."""
        self._restart_reader()
        self.through = through
        self._release_ranges()

    def _restart_reader(self) -> None:
        self._close_reader()
        self.scope = PreparationScope()

    def _close_reader(self) -> None:
        self.runtime.discard_scope(self.scope)

    def _release_ranges(self) -> None:
        self.projection_source.close()
        self.release_held()

    def close(self) -> None:
        self._close_reader()
        self._release_ranges()


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
        # Filter one source page on the model lane. The same bounded pager
        # used for unfiltered history decides which widgets to show.
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

    def result_size(self, result: PreparedTranscriptPage) -> int:
        return result.retained_bytes

    def execute(self) -> PreparedTranscriptPage:
        return PreparedTranscriptPage.prepare(self.page)


@dataclass(frozen=True)
class TranscriptPageWork[Cursor = TranscriptCursor | None](ReusableWork[PreparedTranscriptPage], ScopedWork[PreparedTranscriptPage]):
    scope: PreparationScope
    loader: Callable[..., Awaitable[TranscriptPage]]
    through: Cursor
    request: PageRequest[Cursor]
    lane = WorkLane.MODEL

    @property
    def work_key(self) -> WorkKey:
        # An older page is immutable as its source grows; a newer read ends at the source end.
        return WorkKey(type(self), PageRevision(self.request.end.work_cursor(self.through), self.request), self.scope)

    def result_size(self, result: PreparedTranscriptPage) -> int:
        return result.retained_bytes

    async def execute(
        self: TranscriptPageWork[TranscriptCursor | None], runtime: PreparationRuntime, key: WorkKey,
    ) -> PreparedResult[PreparedTranscriptPage]:
        request = self.request
        page = await request.end.load_page(self.loader, request.cursor, self.through)
        if not request.progressed(page):
            raise ValueError("Transcript history made no cursor progress")
        if self.scope.closed:
            raise asyncio.CancelledError
        prepared = await runtime.renderer.capture(TranscriptPageRenderTask(page))
        return await runtime.run_thread(self.finish_prepared, key, prepared)


class SavedHistory(PreparedPageSource):
    """Prepared pages for a snapshot; storage and work limits belong to the runtime.

    The loader retains ownership of transcript/routing semantics and off-loop
    I/O. CPU preparation uses the application's existing renderer. Foreground
    consumers share in-flight requests; cancelling one waiter cannot release a
    still-running read's slot or publish it into a closed view.
    """

    # The work that reads and prepares one page of this kind of source.
    work: ClassVar[type[TranscriptPageWork]] = TranscriptPageWork

    def __init__(
        self, loader: Callable[..., Awaitable[TranscriptPage]], through: TranscriptCursor,
        runtime: PreparationRuntime,
    ) -> None:
        super().__init__()
        self.loader, self.through, self.runtime = loader, through, runtime
        self.scope = PreparationScope()

    def prefix(self, through) -> PreparedPageSource:
        return SavedPrefix(self, self.loader, through, self.runtime)

    def read_task(self, request: PageRequest) -> TranscriptPageWork:
        return self.work(self.scope, self.loader, self.through, request)

    async def _get(self, request: PageRequest) -> PreparedTranscriptPage:
        result = await self.runtime.submit(self.read_task(request))
        return result.for_view()

    async def _prepare(self, request: PageRequest) -> None:
        await self.runtime.prepare(self.read_task(request))


class SavedPrefix(SavedHistory):
    def __init__(self, earlier, loader, through, runtime):
        super().__init__(loader, through, runtime)
        self.earlier = earlier

    def read_task(self, request):
        # Keep the upstream task's declared native/wire behavior, bounded here.
        return replace(self.earlier.read_task(request), scope=self.scope, through=self.through)

    async def _get(self, request):
        return await request.end.edge((self.earlier.get, super()._get))(request)

    async def _prepare(self, request):
        await request.end.edge((self.earlier.prepare, super()._prepare))(request)


class SourceObservation:
    async def apply(self, history, source) -> bool:
        await history._jump_latest(LatestViewportRequest(LatestPosition.hold(history.window)))
        return not history.undrawn


class Unchanged(SourceObservation):
    async def apply(self, history, source) -> bool:
        if not history.undrawn:
            return (history.pages[-1].prepared.page.after != source.through
                    and await history.extend(source.through))
        return await super().apply(history, source)


class ClosedHistory(PreparedPageSource):
    """A retained range without a saved reader; its pages remain usable."""

    def __init__(self, through, runtime):
        super().__init__()
        self.through, self.runtime = through, runtime
        self.scope = PreparationScope()

    def uses_observation(self, observation) -> bool:
        return False

    async def route_is_current(self) -> bool:
        return False

    def status_thread(self, access):
        from toad.widgets.observed_thread_activity import NoStatusThread

        return NoStatusThread()

    def command_context(self, view):
        return None

    async def submit_input(self, view, event) -> None:
        view.delivery_refused("Conversation source is not ready", event.body)

    def schedule_refresh(self, view):
        return None

    def painted_read(self, history) -> PaintedRead:
        return NothingToRead()

    async def change_style(self, history) -> None:
        return

    async def read_revision(self):
        raise ValueError("This transcript has no saved-source reader")

    async def observe_changes(self, revision):
        return Unchanged()

    def accepts_page(self, current, incoming) -> bool:
        return False

    def seen_page(self, history, seen):
        return None

    async def mark_page(self, page) -> None:
        raise ValueError("This transcript has no saved-source reader")

    async def read_only(self) -> bool:
        return True

    async def update_mentions(self, view) -> None:
        return

    async def status_text(self, *, read_only):
        return "Conversation source is not ready"

    def has_more(self, end, page) -> bool:
        return False

    def has_older(self, page) -> bool:
        return False

    def edge_reached(self, request, boundary) -> bool:
        return True

    async def latest(self, prepared):
        return prepared.for_view()

    def prefix(self, through):
        return ClosedHistory(through, self.runtime)

    async def _get(self, request):
        raise ValueError("This transcript has no saved-source reader")

    async def _prepare(self, request):
        # No saved read can be speculated for a retained-only range.
        return


class ProjectedTranscriptSource(PreparedPageSource, HeldProjection):
    """A projected prefix with a fixed boundary and ordinary bidirectional reads.

    The boundary is the unread prefix of one main page. Earlier reads
    stop at its native before cursor; reaching that cursor forwards returns the
    kept boundary rather than overlapping the main mounted tail.
    Only the boundary and the caller's bounded pages remain strongly kept.
    """

    def measure_projection(self) -> None:
        self.measure_held(self.held_pages, self.projection_source)

    def __init__(
        self, boundary: PreparedTranscriptPage, source: PreparedPageSource,
        projection: TranscriptPageProjection,
    ) -> None:
        super().__init__()
        self.runtime, self.projection = source.runtime, projection
        self.through = boundary.page.after
        self._raw = source.prefix(boundary.page.before)
        self.scope = self._raw.scope
        self._boundary = boundary
        self._projected_boundary: PreparedTranscriptPage | None = None

    async def boundary(self) -> PreparedTranscriptPage:
        if self._projected_boundary is None:
            projected = await self.projection.project(self._boundary, self.runtime)
            self._projected_boundary = replace(projected, page=replace(
                projected.page, has_newer=False,
                has_older=self._raw.has_older(projected.page),
            ))
        return self._projected_boundary

    def prefix(self, through) -> PreparedPageSource:
        return self._raw.prefix(through)

    def _at_boundary(self, request: PageRequest) -> bool:
        boundary = request.end.edge((self.through, self._boundary.page.before))
        return self._raw.edge_reached(request, boundary)

    async def _get(self, request: PageRequest) -> PreparedTranscriptPage:
        if self._at_boundary(request):
            return await self.boundary()
        initial = await self._raw.get(request)
        prepared = await self.projection.project(initial, self.runtime)
        return await request.end.project(self, initial, prepared)

    async def _prepare(self, request: PageRequest) -> None:
        if self._at_boundary(request):
            await self.boundary()
        else:
            await self._raw.prepare(request)

    def _restart_reader(self) -> None:
        self._raw.restart(self._boundary.page.before)
        self.scope = self._raw.scope
        self._projected_boundary = None

    def _close_reader(self) -> None:
        self._raw.close()
        self._raw = ClosedHistory(self.through, self.runtime)
        self._projected_boundary = None
