"""A source's pages read and prepared for drawing, bounded by the reader's demand: the
sources every frontend reads, the ranges a view draws, and the work that prepares a page off
the UI thread. Nothing here draws or imports a toolkit."""

import asyncio
import sys
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from itertools import islice
from pathlib import Path
from typing import ClassVar
from weakref import ReferenceType, ref

from agent_comms.execution.transcript_sources import (
    TranscriptCursor,
    UnreadTranscriptCursor,
)
from agent_comms.messaging.historical_views import (
    ConversationObservation,
    UnobservedConversation,
)
from agent_comms.messaging.message_page import MessagePage
from agent_comms.messaging.sent_message import OutgoingMessageReference
from agent_comms.nominal.field_codec import ContentExclude, FieldCodec
from agent_comms.transcript.transcripts import TranscriptPage
from agent_comms.ui_model.message_category import MessageCategory

from toad.client.connection import CoordinationAccess, Observation
from toad.client.fragments import HistoryFragment
from toad.client.history_preparation import OLDER_END, PageEnd, PageRequest
from toad.client.history_reads import NothingToRead, PaintedRead
from toad.client.history_state import DEFERRED_WORK, SourceWork
from toad.client.input_decision import TranscriptNotReady
from toad.client.submission import ComposeAccess, SubmissionOwner, SubmissionStart, SubmittedText
from toad.commit_claims import RETAINED_SOURCE_CLAIM, CommitClaim, RetainedBlockClaim
from toad.status_thread import NoStatusThread
from toad.work_preparation import (
    PreparationRuntime,
    PreparationScope,
    PreparedResult,
    RetainedBytesStorage,
    ReusableWork,
    ScopedWork,
    ThreadWork,
    UniqueRevision,
    WorkKey,
    WorkLane,
)


WHOLE_PAGE = sys.maxsize
"""Rows asked of a page whose every fragment is wanted, up to the item limit."""


class HoldsRows:
    """Where rows are rendered and kept: the worker processes render them, and the frontend
    holds each as what it draws (styled terminal lines, a Qt row's formatting). A mixin beside
    a native widget, so it declares its hooks without ABC's metaclass.

    Nothing else turns a row's blocks into what is drawn. A row the pager prepares ahead of the
    reader (`HistoryPager.prepare_fragments`) and a row a view finds unprepared as it draws
    (`RowsAsked`) go through the one loop here."""

    @abstractmethod
    async def render_rows(self, waiting: tuple[object, ...]) -> Sequence[object]:
        """One row per waiting unit, rendered in the worker processes."""

    @abstractmethod
    def hold_row(self, waiting: object, row: object) -> None:
        """Keep a rendered row as the unit's rows at the measure it was rendered for."""

    async def render_and_hold(self, waiting: Iterable[object], batch: int,
                           current: Callable[[], bool] = lambda: True) -> None:
        """Render the waiting units, `batch` to a round trip, and hold each row. The work
        stops between batches once it is no longer current (the reader moved on, the page was
        replaced), so superseded work costs at most the batch in flight."""
        waiting = iter(waiting)
        while current():
            units = tuple(islice(waiting, batch))
            if not units:
                return
            rows = await self.render_rows(units)
            if not current():
                return
            for unit, row in zip(units, rows, strict=True):
                self.hold_row(unit, row)


class RowsAsked:
    """Rows a view asks for one at a time, each as it draws a row nothing prepared (an
    arrival, a look that changed in place, a width nothing was prepared at): gathered for one
    turn of the event loop, since a layout asks for many, then prepared together by their
    holder's one loop. A view has no other way to get a row rendered, so none is rendered in
    the process that draws."""

    def __init__(self, holder: HoldsRows, batch: int) -> None:
        self.holder, self.batch = holder, batch
        self.waiting: list[object] = []
        self.sending: asyncio.Handle | None = None
        self.running: set[asyncio.Task[None]] = set()

    def ask(self, unit: object) -> None:
        self.waiting.append(unit)
        if self.sending is None:
            self.sending = asyncio.get_running_loop().call_soon(self.send)

    def send(self) -> None:
        self.sending = None
        waiting, self.waiting = self.waiting, []
        preparing = asyncio.ensure_future(self.holder.render_and_hold(waiting, self.batch))
        self.running.add(preparing)
        preparing.add_done_callback(self.sent)

    def sent(self, preparing: asyncio.Task[None]) -> None:
        """The rows landed, or their render failed. Nothing awaits these rows, so a failure is
        raised here, into the loop's error report: rows left plain with no error were the
        failure nobody saw."""
        self.running.discard(preparing)
        if not preparing.cancelled():
            preparing.result()

    def drop(self) -> None:
        """Forget the rows asked for and not yet sent."""
        self.waiting.clear()
        if self.sending is not None:
            self.sending.cancel()
            self.sending = None

    def stop(self) -> None:
        """Nothing lands after this: the rows being rendered are let go."""
        for preparing in tuple(self.running):
            preparing.cancel()


class MeasuresFragments(HoldsRows):
    """Where fragments are measured: the rows a fragment takes there at the current width, in
    that frontend's own unit.

    It is also where a fragment's rows are prepared before they are measured: the pager's
    loop (`HistoryPager.prepare_fragments`) asks it which fragments still wait and has them
    rendered and held (`HoldsRows.render_and_hold`)."""

    @abstractmethod
    def fragment_height(self, fragment: HistoryFragment) -> int: ...

    @property
    @abstractmethod
    def measurable(self) -> bool:
        """Whether this destination has a width yet; before its first layout, nothing can
        be prepared for it."""

    @abstractmethod
    def unprepared(self, fragment: HistoryFragment) -> tuple[object, ...]:
        """The fragment as this destination will render it, when its rows at the current
        measure are not held yet; nothing when they are."""


class DrawnPage:
    """A native view drawing one prepared page's range; a range change asks it to measure again."""

    prepared: PreparedTranscriptPage

    @abstractmethod
    def range_changed(self) -> None: ...


@dataclass
class PreparedTranscriptPage:
    """One transcript page's immutable fragments and the range a view draws."""

    page: TranscriptPage
    fragments: tuple[HistoryFragment, ...]
    retained_bytes: int
    outgoing_coverage: frozenset[OutgoingMessageReference] = field(kw_only=True)
    fragment_range: tuple[int, int] | None = None

    def __deepcopy__(self, memo):
        """Copy page-local fields; keep the original source and fragments."""
        return replace(self)

    @classmethod
    def measured(cls, page, fragments: tuple[HistoryFragment, ...], **view):
        coverage = frozenset(reference for fragment in fragments
                             for reference in fragment.outgoing_sources)
        prepared = cls(page, fragments, 0, outgoing_coverage=coverage, **view)
        prepared.measure_sources()
        return prepared

    @property
    def source_payload_bytes(self) -> int:
        return sum(256 + 4 * event.text_size for event in self.page.events)

    def measure_sources(self) -> None:
        """The page owns its events; each fragment owns only its acquired rows."""
        self.retained_bytes = (256 + 64 * len(self.outgoing_coverage)
                               + self.source_payload_bytes
                               + sum(fragment.retained_bytes for fragment in self.fragments))

    @classmethod
    def empty(cls, page):
        return cls.measured(page, ())

    def project(self, fragments: tuple[HistoryFragment, ...]):
        if len(fragments) == len(self.fragments) and all(
                selected is original for selected, original in zip(fragments, self.fragments)):
            return self.for_view()
        return type(self).measured(self.page, fragments)

    def configure(self, *, batch_size: int) -> None:
        if self.fragment_range is None:
            self.set_fragment_range(slice(max(0, len(self.fragments) - batch_size), len(self.fragments)))

    @property
    def fragments_in_range(self):
        return self.fragments[self.start:self.stop]

    async def prepare_rows(self, view, current: Callable[[], bool], *,
                           target: MeasuresFragments, selected: frozenset[type[MessageCategory]],
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
                take += 1
                start, stop = min(start, index), max(stop, index + 1)
                rows += (target.fragment_height(fragment)
                         if fragment.shown_in(selected) else 0)
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
    async def extend(
        self, view: DrawnPage, prepared: PreparedTranscriptPage, current: Callable[[], bool],
    ) -> bool:
        """Accept the staged rows; the range owner alone combines its membership."""
        if not current():
            return False
        if prepared.fragments is not self.fragments:
            raise ValueError("Transcript input replacement requires a new prepared page")
        selected = slice(min(self.start, prepared.start), max(self.stop, prepared.stop))
        return self.replace_range(view, selected, current)

    def replace_range(self, view: DrawnPage, selected: slice, current: Callable[[], bool]) -> bool:
        if not current():
            return False
        if self.fragment_range != (selected.start, selected.stop):
            self.set_fragment_range(selected)
            view.range_changed()
        return True

    def same_source(self, other: PreparedTranscriptPage) -> bool:
        """Keep original suppliers only when declared page content is unchanged."""
        # Filtered/restyled results must retain their distinct supplier tuples.
        # Core's content projection excludes read annotations without discarding
        # the fresh witness carried by each acquired page.
        return (self.fragments is other.fragments
                and FieldCodec.project(self.page, ContentExclude)
                == FieldCodec.project(other.page, ContentExclude))

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
    members: tuple[HistoryFragment, ...] = field(repr=False)

    def __eq__(self, other):
        if not isinstance(other, PageFragmentRange):
            return NotImplemented
        return ((page := self.page()) is not None and page is other.page()
                and self.start == other.start and self.stop == other.stop)


@dataclass(frozen=True)
class FilteredTranscriptBatch:
    prepared: PreparedTranscriptPage
    stop: int


@dataclass(frozen=True)
class TranscriptFilterWork(ThreadWork[FilteredTranscriptBatch]):
    """Select the next bounded presentation batch off-loop from source data."""

    page: PreparedTranscriptPage
    fragments: tuple[HistoryFragment, ...]
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


class PreparedPageSource:
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

    async def for_rebuild(self) -> PreparedPageSource:
        """An ordinary parked source keeps its original pages."""
        return self

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

    async def accept_page(
        self, history, edge: DrawnPage, prepared: PreparedTranscriptPage,
    ) -> bool:
        """Immutable saved reads already carry their validated source cut."""
        return True

    @abstractmethod
    async def _get(self, request: PageRequest) -> PreparedTranscriptPage: ...

    async def prepare(self, request: PageRequest) -> None:
        if not self.closed:
            await self._prepare(request)

    @abstractmethod
    async def _prepare(self, request: PageRequest) -> None: ...

    def reload_key(self):
        return self.scope

    @property
    def commit_claim(self) -> CommitClaim:
        return RETAINED_SOURCE_CLAIM

    def contains(self, cursor: TranscriptCursor) -> bool:
        return self.through.contains(cursor)

    def accepts_commit(self, cursor: TranscriptCursor) -> bool:
        return cursor.contains(self.through)

    def has_more(self, end: PageEnd, page: TranscriptPage) -> bool:
        return end.has_more(self.through, page)

    def has_older(self, page: TranscriptPage) -> bool:
        return page.has_older

    def edge_reached(self, request: PageRequest, boundary) -> bool:
        return request.cursor == boundary

    async def latest(self, prepared: PreparedTranscriptPage) -> PreparedTranscriptPage:
        if prepared.page.after.same_position(self.through):
            return prepared.for_view()
        return (await self.get(PageRequest(OLDER_END, self.through))).for_view()

    @abstractmethod
    def prefix(self, through: TranscriptCursor) -> PreparedPageSource: ...

    async def prepare_next(self, page: TranscriptPage, end: PageEnd) -> None:
        if self.has_more(end, page):
            await self.prepare(end.adjacent(page))

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

    def fragments_for(self, page: PreparedTranscriptPage):
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

    def fragments_for(self, page: PreparedTranscriptPage):
        if self.boundary.page() is page:
            return self.boundary.members
        return super().fragments_for(page)


class TranscriptNoProgress(ValueError):
    """A page read returned no new edge while its end still claimed more."""

    def __init__(self, request: PageRequest, through: TranscriptCursor, page: TranscriptPage) -> None:
        super().__init__(
            f"Transcript history made no cursor progress: {type(request.end).__name__} "
            f"from {request.cursor!r} through {through!r} returned before={page.before!r} "
            f"after={page.after!r} has_older={page.has_older} has_newer={page.has_newer} "
            f"events={len(page.events)}")


@dataclass(frozen=True)
class SourcePageWork[Cursor = TranscriptCursor](RetainedBytesStorage[PreparedTranscriptPage], ReusableWork[PreparedTranscriptPage], ScopedWork[PreparedTranscriptPage]):
    """Read and prepare one page of a source off the UI thread; each kind of source owns how."""

    scope: PreparationScope
    loader: Callable[..., Awaitable[TranscriptPage]]
    through: Cursor
    request: PageRequest[Cursor]
    lane = WorkLane.MODEL

    @property
    def work_key(self) -> WorkKey:
        # An older page is immutable as its source grows; a newer read ends at the source end.
        return WorkKey(type(self), self.request.end.work_revision(self.request, self.through), self.scope)

    @abstractmethod
    async def execute(self, runtime: PreparationRuntime, key: WorkKey) -> PreparedResult[PreparedTranscriptPage]: ...


@dataclass(frozen=True)
class UnreadTranscriptPage:
    """The view before a saved page has been read, not a storage snapshot."""

    events: tuple = ()
    before: TranscriptCursor = field(default_factory=UnreadTranscriptCursor)
    after: TranscriptCursor = field(default_factory=UnreadTranscriptCursor)
    has_older: bool = False
    has_newer: bool = False


class ReplaceablePageSource(PreparedPageSource):
    """A complete source can prepare another reading without closing this one."""

    @abstractmethod
    def replacement(self, through) -> ReplaceablePageSource: ...

    @abstractmethod
    async def route_is_current(self) -> bool:
        """Whether the route still selects this source. ``WirePageBuffer`` checks the
        live wire; ``ClosedHistory`` always returns False; ``SavedHistory`` is always
        True (a saved snapshot IS what you asked for). Declared abstract here so any
        new ``ReplaceablePageSource`` subclass has to answer; the caller
        ``HistoryReads.source_is_current`` depends on every source satisfying it."""

    def reads_from(self, root: str | Path) -> bool:
        """Whether this reader reads a conversation from ``root``; a closed one reads none."""
        return False

    def style_differs(self, style) -> bool:
        """Whether the messages are drawn in a style other than ``style``: a source that
        draws no bus messages (a closed or saved transcript) has none to restyle."""
        return False

    async def restyle_to(self, history, style) -> None:
        """Draw the bus messages in ``style``; a source drawing none has nothing to do."""


class SavedHistory(ReplaceablePageSource):
    """Prepared pages for a snapshot; storage and work limits belong to the runtime.

    The loader retains ownership of transcript/routing semantics and off-loop
    I/O. CPU preparation uses the application's existing renderer. Foreground
    consumers share in-flight requests; cancelling one waiter cannot release a
    still-running read's slot or publish it into a closed view.

    `fragments` carries the frontend's fragment-flavor choice (Textual's draw-path
    subclasses or Qt's row-paint subclasses) through to the render task without
    forwarders restating it.
    """

    # The work that reads and prepares one page of this kind of source.
    work: ClassVar[type[SourcePageWork]]

    def __init__(
        self, loader: Callable[..., Awaitable[TranscriptPage]], through: TranscriptCursor,
        runtime: PreparationRuntime, *, fragments,
    ) -> None:
        super().__init__()
        self.loader, self.through, self.runtime = loader, through, runtime
        self.fragments = fragments
        self.scope = PreparationScope()

    def prefix(self, through) -> PreparedPageSource:
        return SavedPrefix(self, self.loader, through, self.runtime, fragments=self.fragments)

    def replacement(self, through) -> SavedHistory:
        return type(self)(self.loader, through, self.runtime, fragments=self.fragments)

    async def route_is_current(self) -> bool:
        """A saved snapshot IS the route — the file doesn't move under us."""
        return True

    def read_task(self, request: PageRequest) -> SourcePageWork:
        return self.work(self.scope, self.loader, self.through, request, self.fragments)

    async def _get(self, request: PageRequest) -> PreparedTranscriptPage:
        result = await self.runtime.submit(self.read_task(request))
        return result.for_view()

    async def _prepare(self, request: PageRequest) -> None:
        await self.runtime.prepare(self.read_task(request))


class SavedPrefix(SavedHistory):
    def __init__(self, earlier: SavedHistory, loader: Callable[..., Awaitable[TranscriptPage]], through, runtime: PreparationRuntime, *, fragments) -> None:
        super().__init__(loader, through, runtime, fragments=fragments)
        self.earlier = earlier

    def replacement(self, through) -> SavedHistory:
        # A replacement reads the complete source; it must not delegate older
        # reads to the superseded prefix's preparation scope.
        return self.earlier.replacement(through)

    def read_task(self, request: PageRequest):
        # Keep the upstream task's declared native/wire behavior, bounded here.
        return replace(self.earlier.read_task(request), scope=self.scope, through=self.through)

    async def _get(self, request: PageRequest):
        return await request.end.edge((self.earlier.get, super()._get))(request)

    async def _prepare(self, request: PageRequest) -> None:
        await request.end.edge((self.earlier.prepare, super()._prepare))(request)


class RetainedPageSource:
    """A local entry closed this source range; later commits cannot replace it."""

    @property
    def commit_claim(self) -> CommitClaim:
        return RetainedBlockClaim()


class FrozenSavedPrefix(RetainedPageSource, SavedPrefix):
    """The ordinary saved pager, bounded where a local entry arrived."""

    def close(self) -> None:
        super().close()
        self.earlier.close()


class SourceObservation:
    async def apply(self, history, source: ReplaceablePageSource) -> bool:
        await history.publish_held_latest()
        return not history.undrawn


class Unchanged(SourceObservation):
    async def apply(self, history, source: ReplaceablePageSource) -> bool:
        if not history.undrawn:
            return (history.pages[-1].prepared.page.after != source.through
                    and await history.extend(source.through))
        return await super().apply(history, source)


class ClosedHistory(ReplaceablePageSource):
    """A retained range without a saved reader; its pages remain usable."""

    revision = UnobservedConversation()

    def __init__(self, through: TranscriptCursor, runtime: PreparationRuntime) -> None:
        super().__init__()
        self.through, self.runtime = through, runtime
        self.scope = PreparationScope()

    def uses_observation(self, observation: Observation) -> bool:
        return False

    async def route_is_current(self) -> bool:
        return False

    def status_thread(self, access: CoordinationAccess):
        return NoStatusThread()

    def command_context(self, view):
        return None

    def refresh_identity(self, view) -> None:
        """A closed history reads no root; a retired view has no references to follow."""

    def begin_submission(
        self, view, owner: SubmissionOwner, submission: SubmittedText
    ) -> SubmissionStart:
        return owner.unbound(submission, TranscriptNotReady())

    def schedule_refresh(self, view) -> SourceWork:
        return DEFERRED_WORK

    def painted_read(self, history) -> PaintedRead:
        return NothingToRead()

    async def change_style(self, history) -> None:
        return

    async def read_revision(self):
        raise ValueError("This transcript has no saved-source reader")

    async def observe_changes(self, revision: ConversationObservation):
        return Unchanged()

    def seen_page(self, history, seen: tuple[HistoryFragment, ...]):
        return None

    async def mark_page(self, page: MessagePage) -> None:
        raise ValueError("This transcript has no saved-source reader")

    async def compose_access(self) -> ComposeAccess:
        """A source not yet ready holds compose, and takes nothing."""
        return ComposeAccess(read_only=True, takes_files=False)

    async def update_mentions(self, view) -> None:
        return

    async def status_text(self, *, read_only: bool) -> str:
        return "Conversation source is not ready"

    def has_more(self, end: PageEnd, page) -> bool:
        return False

    def has_older(self, page) -> bool:
        return False

    def edge_reached(self, request: PageRequest, boundary) -> bool:
        return True

    async def latest(self, prepared: PreparedTranscriptPage):
        return prepared.for_view()

    def prefix(self, through):
        return ClosedHistory(through, self.runtime)

    def replacement(self, through) -> ClosedHistory:
        return ClosedHistory(through, self.runtime)

    async def _get(self, request: PageRequest):
        raise ValueError("This transcript has no saved-source reader")

    async def _prepare(self, request: PageRequest) -> None:
        # No saved read can be speculated for a retained-only range.
        return


class FrozenClosedHistory(RetainedPageSource, ClosedHistory):
    """A local entry before any saved source retains only the empty prefix."""

    async def latest(self, prepared: PreparedTranscriptPage) -> PreparedTranscriptPage:
        return prepared.for_view()


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

    def _close_reader(self) -> None:
        self._raw.close()
        self._raw = ClosedHistory(self.through, self.runtime)
        self._projected_boundary = None


class _DrawingStopped(Exception):
    """Unwind a source publication that no longer owns its drawing."""
