"""A history's pages within its reader window, as every frontend pages them.

The pager reads one source range per pass at the end the reader travels toward, keeps
the fragments the reader sees and evicts the rest, publishes the newest rows as one
destination, and follows the end while the reader does. Read-ahead measures the
reader's travel and predicts how far ahead to prepare. The frontend draws the pages,
measures rows and owns the scroll widget; this module imports no toolkit.
"""
import asyncio
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from contextlib import AsyncExitStack
from dataclasses import dataclass, fields, replace
from functools import partial
from math import ceil
from operator import ge, gt
from time import get_clock_info, monotonic
from typing import Annotated, ClassVar, get_args

from agent_comms.execution.transcript_sources import TranscriptCursor
from agent_comms.transcript.transcripts import TranscriptPage
from agent_comms.ui_model.message_category import MessageCategory, all_categories

from agent_comms.messaging.message_reference import MessageReference
from toad.client.fragments import FragmentKey, HistoryFragment
from toad.client.history_changes import NO_BURST, ArrivalBurst
from toad.client.history_preparation import (
    NEWER_END,
    OLDER_END,
    HistorySourceSnapshot,
    PageEnd,
)
from toad.client.source_resumption import ResumesSource
from toad.client.history_state import (
    LatestViewportRequest,
    LatestViewportState,
    LiveTranscript,
    NoLatestRequest,
    ParkedSourceTranscript,
    ReplacementViewportRequest,
    RetiredSourceTranscript,
    SourceWork,
    TranscriptState,
    WorkingTranscript,
)
from toad.client.prepared_pages import (
    DrawnPage,
    MeasuresFragments,
    PreparedPageSource,
    PreparedTranscriptPage,
    _DrawingStopped,
)
from toad.client.reader_position import LatestPosition, ReaderWindow
from toad.client.resource_release import ResourceRelease
from toad.core.source_events import TranscriptSourceWorkFinished
from toad.transcript_filter import FilterState


@dataclass(frozen=True)
class PresentationBudget:
    """Tunable working-set policy, not transport-page or source-size limits.

    Visible and explicitly protected items may exceed the nominal item budget.
    Loading stays bounded by separate limits; source data is never discarded to
    satisfy a widget budget.
    """

    max_items: Annotated[int, gt] = 24
    batch_items: Annotated[int, gt] = 4
    reserve_batches: Annotated[int, ge] = 4
    minimum_widgets: Annotated[int, gt] = 300
    widgets_per_row: Annotated[int, ge] = 10
    buffer_viewports: Annotated[int, gt] = 3
    destination_pages: Annotated[int, gt] = 2
    lookahead_seconds: Annotated[float, gt] = 1.0
    delivery_safety_factor: Annotated[float, gt] = 2.0
    scroll_idle_seconds: Annotated[float, gt] = 0.2

    def __post_init__(self) -> None:
        for declaration in fields(self):
            value = getattr(self, declaration.name)
            numeric_type, bound = get_args(declaration.type)
            # Python permits an integer wherever a float is declared, but a
            # bool is not a numeric budget. The declaration supplies the bound.
            if type(value) not in (numeric_type, int) or not bound(value, 0):
                raise ValueError(f"{declaration.name} violates its declared {bound.__name__} zero bound")

    def item_limit(self, protected_items: int) -> int:
        return max(self.max_items, protected_items + self.reserve_batches * self.batch_items)

    def widget_limit(self, viewport_rows: int) -> int:
        return max(self.minimum_widgets, viewport_rows * self.widgets_per_row)

    def can_read_destination(self, pages: int) -> bool:
        """A bottom destination has bounded source reads, even for sparse rows."""
        return pages < self.destination_pages

    def runway_rows(self, viewport_rows: int) -> int:
        return max(1, viewport_rows) * self.buffer_viewports

    def fit(self, candidates: Iterable[NativePresentation], required: tuple[NativePresentation, ...],
            viewport_rows: int, max_bytes: int) -> set[NativePresentation]:
        """Visible/protected native bodies first, then ordered bounded resources."""
        kept = set(required)
        widgets = source_bytes = 0
        for owner in candidates:
            count = owner.retained_widget_count
            size = owner.retained_source_bytes + owner.retained_paint_bytes
            if owner not in kept:
                if (widgets + count > self.widget_limit(viewport_rows)
                        or source_bytes + size > max_bytes):
                    continue
                kept.add(owner)
            widgets += count
            source_bytes += size
        return kept

    def runway(self, sequence, first: int, last: int, viewport_rows: int):
        """Native measured bodies on both sides, including stationary reversal."""
        before, after = [], []
        for candidates, selected in ((reversed(sequence[:first]), before),
                                     (iter(sequence[last:]), after)):
            rows = 0
            for owner in candidates:
                selected.append(owner)
                rows += max(1, owner.measured_rows)
                if rows >= self.runway_rows(viewport_rows):
                    break
        # Nearest first on both sides; a side that has run out contributes nothing.
        return [owner for index in range(max(len(before), len(after)))
                for owner in (*before[index:index + 1], *after[index:index + 1])]


@dataclass(frozen=True)
class NewDestination:
    """A latest-destination range no mounted page draws yet: a new page is acquired for it."""

    prepared: PreparedTranscriptPage

    async def page_view(self, history, acquisition: AsyncExitStack, views, current, edge) -> DrawnPage:
        return await acquisition.enter_async_context(type(edge).acquire(
            history, self.prepared, end=OLDER_END, pages=views, current=current,
        ))

    def keep(self, current: Callable[[], bool]) -> None:
        """A new page already holds exactly this range."""


@dataclass(frozen=True)
class KeptDestination(NewDestination):
    """A mounted page already draws this source: it keeps its fragments, prepared lines and documents."""

    view: DrawnPage

    async def page_view(self, history, acquisition: AsyncExitStack, views, current, edge) -> DrawnPage:
        return self.view

    def keep(self, current: Callable[[], bool]) -> None:
        if not self.view.prepared.replace_range(
            self.view, slice(self.prepared.start, self.prepared.stop), current,
        ):
            raise _DrawingStopped
        self.view.prepared.page = self.prepared.page


class PagingWindow(ReaderWindow):
    """The reader window a history pages within: its lock, budget, read-ahead and the
    geometry read-ahead asks it for. A plain parent beside the toolkit's scroll widget,
    whose own members answer first: list it after that widget, which its hooks would
    otherwise hide from super()."""

    histories: set
    scroll_target_y: float
    max_scroll_y: float
    arrival_burst: ArrivalBurst = NO_BURST
    """The messages that last arrived together at the end the reader follows."""

    def arrivals_followed(self, arrivals: tuple[HistoryFragment, ...]) -> None:
        """`arrivals` were published at the followed end: they join the burst while the reader
        follows it, or while the burst is still arriving (Textual stops following where it
        shows a tall arrival from its head)."""
        if arrivals and (self.follows_tail or self.arrival_burst.live(monotonic())):
            self.arrival_burst = self.arrival_burst.arrived(arrivals, monotonic())
    lookahead: DirectionalPreparation
    presentation_budget: PresentationBudget
    configuration_state: object
    """The settings of the view this window reads in: its override, else the app's."""

    def apply_buffer_viewports(self) -> None:
        """The history buffer setting changed: prepare and keep that many viewports on
        both sides of the reader (the `history_buffer_viewports` effect)."""
        value = self.configuration_state.fields.ui.history_buffer_viewports
        if value != self.presentation_budget.buffer_viewports:
            self.presentation_budget = replace(self.presentation_budget, buffer_viewports=value)
            self.request_preparation()

    @abstractmethod
    def check_follow(self) -> None:
        """Follow the end again when the reader has scrolled back to it."""

    @abstractmethod
    def preserve_history(self):
        """An async context in which pages change while the reader's row stays put."""

    @abstractmethod
    def request_preparation(self) -> None:
        """Prepare the viewport again on the next frame."""

    @abstractmethod
    def _schedule_settle(self) -> None:
        """End the reader's measured travel once input has been idle."""

    @abstractmethod
    def runway(self, history) -> OffScreenRunway:
        """Published rows of `history` above and below the viewport, or that it is off screen."""

    @property
    @abstractmethod
    def animated_travel(self) -> float:
        """Rows a scroll animation still has to travel."""

    @property
    @abstractmethod
    def viewport_rows(self) -> int: ...

    @property
    @abstractmethod
    def content_rows(self) -> int:
        """Rows of the viewport the history's content may fill."""

    @property
    @abstractmethod
    def unfilled_rows(self) -> int:
        """Viewport rows below the last drawn row: a hole to fill without scroll input."""

    @property
    @abstractmethod
    def presenting(self) -> bool:
        """Whether the window is on the screen the reader is looking at."""


class ReaderPlacement:
    """What every frontend's PagingWindow does with its answers: End, settling the reader's
    travel and placing the reader. A concrete mixin with no base, so a window lists it
    before contracts that only declare jump_to_latest while PagingWindow's hooks stay
    after its scroll widget, out of super()'s way."""

    def jump_to_latest(self) -> None:
        """Follow the source tail, including pages outside the mounted window."""
        latest = LatestPosition.hold(self)
        self.destination()
        for history in tuple(self.histories):
            if NEWER_END.visible_more(history):
                history.request_latest(latest)

    def destination(self) -> None:
        """End: prepare the destination in one burst, not every page between."""
        self.lookahead.observe(self.scroll_y)
        self.lookahead.destination(self.viewport_rows)
        self.request_preparation()

    def _settle(self) -> None:
        self.lookahead.settle()
        self.request_preparation()

    def latest_limits(self, budget: PresentationBudget) -> tuple[int, int]:
        """One native destination's row capacity and bounded fragment budget."""
        return (self.presentation_budget.runway_rows(self.viewport_rows),
                self.lookahead.destination_batch(budget, self.viewport_rows))

    def place_reader(self) -> bool:
        """Put the reader on the kept position in the layout just made; True when that scrolled the window.

        A layout runs over loop turns and the reader can scroll meanwhile.
        Their movement shifts the kept position, so the position kept now is
        the one placed. One that names widgets this layout did not measure
        (kept after the layout started) is placed by the layout that follows.
        """
        position = self.reader_position
        if not position.laid_out(self):
            return False
        previous = self.scroll_y
        with self.layout_scroll():
            self.reader_position = position.placed(self, position.place(self))
        return self.scroll_y != previous

    def follow_latest(self) -> None:
        """Follow the latest message on a request the reader already made; not a new movement."""
        with self.layout_scroll():
            self.anchor()


class HistoryPager(ResumesSource):
    """One history's pages of one source, within a reader window.

    The frontend's history answers the hooks below with its widgets: which window holds
    it, how a page is drawn, measured, shown and retired, and when the next frame comes.
    A plain parent beside the native history, so its hooks are declared without ABC's
    metaclass; NativePager declares what the toolkit's own base answers.
    """

    DEFAULT_BUDGET = PresentationBudget(max_items=240)

    pages: deque[DrawnPage]
    _source_state: TranscriptState
    filter: FilterState
    budget: PresentationBudget
    page_view_type: type[DrawnPage]

    # What the frontend's history answers

    @property
    @abstractmethod
    def window(self) -> PagingWindow: ...

    @property
    @abstractmethod
    def can_draw_on_screen(self) -> bool: ...

    @property
    @abstractmethod
    def source_identity(self) -> object: ...

    @abstractmethod
    def source_snapshot(self) -> HistorySourceSnapshot: ...

    @abstractmethod
    def followed_here(self) -> None:
        """Register with the window drawing these pages."""

    @abstractmethod
    def request_preparation(self) -> None:
        """Prepare this source's viewport on the next frame."""

    @abstractmethod
    def visible_fragments(self) -> tuple[HistoryFragment, ...]: ...

    @abstractmethod
    def prepare_visible_pages(self) -> None:
        """Let the pages on screen consume the geometry just committed."""

    @abstractmethod
    async def prepare_fragments(self, fragments: tuple[HistoryFragment, ...], current: Callable[[], bool], *,
                                selected: frozenset[type[MessageCategory]], target: MeasuresFragments) -> None:
        """Render fragments against the native destination before they are measured."""

    @abstractmethod
    def hold_arrival(self, arrivals: tuple[HistoryFragment, ...]) -> None:
        """Hold rows that arrive below a following reader until they are drawn."""

    @abstractmethod
    def _update_edges(self) -> None:
        """Show or hide the controls at each end for rows not loaded yet."""

    @abstractmethod
    def read_ahead(self, work: Callable[[], Awaitable[object]]) -> None:
        """Run one read-ahead of the next page, replacing a running one."""

    @abstractmethod
    def cancel_work(self) -> list:
        """Cancel this history's running source work; return what to join."""

    @abstractmethod
    def joined(self, workers: list) -> Awaitable[None]:
        """Join cancelled work independently of the caller."""

    @classmethod
    def initial_state(cls, view) -> TranscriptState:
        return LiveTranscript()

    def __init__(self, *args, source_state: TranscriptState, page_source: PreparedPageSource, **kwargs):
        self._source_state = source_state
        self._generation = 0
        self.page_source = page_source
        self._source_observation = ResourceRelease()
        self.latest: LatestViewportState = NoLatestRequest()
        super().__init__(*args, **kwargs)

    @property
    def state(self) -> TranscriptState:
        return self._source_state.observed(self)

    def _require_can_draw(self) -> None:
        if not self.state.can_draw:
            raise _DrawingStopped

    @property
    def blocks_visible_read(self) -> bool:
        """Source mutation, remaining tail and filtering govern acknowledgement."""
        return self.state.blocks_visible_read(self)

    @property
    def source_ready(self) -> bool:
        return self.state.source_ready(self)

    def reserve_source_work(
        self, operation: type[WorkingTranscript] | partial[WorkingTranscript] = WorkingTranscript
    ) -> WorkingTranscript:
        operation = self._source_state.reserve(self, operation)
        self._source_state = operation
        return operation

    def schedule_source_work(self, work) -> SourceWork:
        """Own source I/O on the pager worker, never its caller's event pump."""
        return self.state.schedule_work(self, work)

    def observe_source(self) -> None:
        self.followed_here()
        self.request_preparation()

    def close(self) -> None:
        from toad.client.prepared_pages import ClosedHistory

        source = self.page_source
        source.close()
        self.page_source = ClosedHistory(source.through, source.runtime)

    async def close_source_reader(self) -> None:
        """Close source subscriptions without releasing the separately held pages."""

    def request_page(self, end) -> None:
        self.schedule_source_work(partial(self._prepare_edge, end))

    @property
    def follows_source_tail(self) -> bool:
        return self.window.follows_tail

    def has_more(self, end: PageEnd) -> bool:
        page = end.edge(self.pages).prepared
        return end.can_extend(page) or self.page_source.has_more(end, page.page)

    async def _prepare_edge(self, end) -> None:
        """Load one source range per pass, so a catch-up forms across frames.

        Looping here until the edge is satisfied loads the whole missed run in one
        worker pass, without returning to the event pump until it is done: a reader
        who comes back sees nothing, then everything. Asking the next frame for the
        rest lets the messages form as they arrive, and the same total number of
        pages is read either way.
        """
        snapshot = self.source_snapshot()
        if snapshot.current(self) and await self._load_page(end):
            self.request_preparation()

    def request_latest(self, destination: LatestPosition) -> None:
        # End supersedes any admitted edge publication. Its worker may finish
        # the source read, but the old snapshot cannot paint an intermediate page.
        self._generation += 1
        self.state.request_latest(self, LatestViewportRequest(destination))

    async def jump_latest(self, request: LatestViewportRequest,
                           publication_current: Callable[[], bool] = lambda: True) -> bool:
        """Publish one destination using its captured source and reader position.

        A preceding page's restoration may have left the window off its tail.
        Apply the still-current destination before its source read, then finish
        native geometry after publication. Neither restoration is another user
        scroll; movement during I/O invalidates the captured request revision.
        """
        if not request.current(self.window):
            return False
        if not self.can_draw_on_screen:
            self.latest = request.defer(self)
            return False
        request.restore(self.window)
        snapshot = self.source_snapshot()
        current = lambda: snapshot.current(self) and request.current(snapshot.window) and publication_current()
        with request.reading(self) as (source, release):
            prepared = await request.page(self, source)
            if await self._publish_latest(current, source, prepared, release):
                # Capture the source accepted with the destination's pages.
                self.call_after_refresh(self._complete_latest, self.source_snapshot(), request)
                return True
        self.latest = request.defer(self)
        return False

    async def publish_held_latest(self, publication_current: Callable[[], bool] = lambda: True) -> bool:
        """Publish the newest rows, holding the reader on them until their source settles."""
        return await self.jump_latest(LatestViewportRequest(LatestPosition.hold(self.window)), publication_current)

    async def _publish_latest(self, current: Callable[[], bool],
                              source: PreparedPageSource, prepared: PreparedTranscriptPage,
                              release: ResourceRelease) -> bool:
        """Prepare the bottom destination, keeping views of unchanged source pages."""
        window = self.window
        edge = self.pages[-1]
        latest = prepared
        rows, limit = window.latest_limits(self.budget)
        pages_read = 1
        destination: list[NewDestination] = []
        while rows > 0 and limit > 0:
            existing = next((KeptDestination(prepared, view) for view in self.pages
                             if view.prepared.same_source(prepared)), NewDestination(prepared))
            rows -= await prepared.prepare_rows(
                self, current, target=self, selected=self.selected_categories,
                boundary=len(prepared.fragments), end=OLDER_END,
                rows_needed=rows, limit=limit,
            )
            if not current():
                return False
            take = prepared.stop - prepared.start
            if take:
                destination.insert(0, existing)
            limit -= take
            if rows <= 0:
                break
            if (not source.has_older(prepared.page) or limit <= 0
                    or not window.presentation_budget.can_read_destination(pages_read)):
                break
            prepared = (await source.get(OLDER_END.adjacent(prepared.page))).for_view()
            pages_read += 1
        async with window.history_lock:
            if not current() or self.pages[-1] is not edge:
                return False
            async with window.preserve_history():
                previous = tuple(self.pages)
                views = deque()
                if not destination:
                    # An empty answer is published too: the edge draws nothing,
                    # at its end. `latest` was never ranged by the loop above.
                    latest.set_fragment_range(slice(len(latest.fragments), len(latest.fragments)))
                    destination.append(NewDestination(latest))
                try:
                    async with AsyncExitStack() as acquisition:
                        for target in reversed(destination):
                            views.appendleft(await target.page_view(self, acquisition, views, current, edge))
                        # Keep existing fragments, prepared lines and documents.
                        for target in destination:
                            target.keep(current)
                        previous_source = self.page_source
                        self.page_source, self.pages = source, views
                        source.through = latest.page.after
                        release.pop_all()
                        if previous_source is not source:
                            release.callback(previous_source.close)
                            self.filter = self.filter.changed()
                except _DrawingStopped:
                    return False
                retired = tuple(page for page in previous if page not in views)
                for page in retired:
                    page.display = False
                self._update_edges()
                self.rows_published()
                await self.remove_children(retired)
            return True

    @property
    def drawn_end_more(self) -> bool:
        """Rows below the drawn end that the reader was already shown exist: prepared ones, or a known newer page.

        Source rows a commit adds beyond the drawn end are not among them; they arrive.
        """
        edge = self.pages[-1].prepared
        return NEWER_END.can_extend(edge) or edge.page.has_newer

    async def publish_append(self, through: TranscriptCursor, publication_current: Callable[[], bool]) -> bool:
        """A commit may retire live blocks only after publishing its destination.

        extend also serves held readers: its True can mean access advanced
        without new paint. A followed commit must instead finish a known gap
        through the existing bounded destination owner before reporting success.
        """
        if not await self.extend(through, publication_current):
            return False
        if not publication_current():
            return False
        if self.drawn_end_more:
            if not await self.publish_held_latest(publication_current):
                return False
        return (publication_current() and not self.drawn_end_more
                and self.pages[-1].prepared.page.after.same_position(through))

    async def extend(self, through, publication_current: Callable[[], bool] = lambda: True) -> bool:
        """Extend source access, preserving held readers that have not drawn its end."""
        if not publication_current():
            return False
        self.page_source.through = through
        edge = self.pages[-1]
        if edge.prepared.page.after == self.page_source.through:
            return True
        if self.drawn_end_more:
            if await self.window.reader_position.source_arrived(self):
                return True
            if not edge.prepared.page.has_newer:
                edge.prepared.page = replace(edge.prepared.page, has_newer=True)
            return True
        snapshot = self.source_snapshot()
        prepared = await self.page_source.get(NEWER_END.adjacent(edge.prepared.page))
        if not await self.source_is_current(snapshot) or not publication_current():
            return False
        if self.pages[-1] is not edge:
            return False
        if not await self.page_source.accept_page(self, edge, prepared):
            return False
        if not prepared.fragments:
            NEWER_END.advance_empty(edge.prepared, prepared)
        elif not self.window.follows_tail:
            edge.prepared.page = replace(edge.prepared.page, has_newer=True)
            self._update_edges()
        else:
            await self._load_page(NEWER_END, publication_current)
            if not snapshot.current(self) or not publication_current():
                return False
            tail = self.pages[-1]
            if tail.prepared.page.after != self.page_source.through:
                # Rejected preparation still leaves the source gap reachable.
                tail.prepared.page = replace(tail.prepared.page, has_newer=True)
                self._update_edges()
            if self.pages[-1].prepared.page.has_newer and self.window.follows_tail:
                await self.publish_held_latest(publication_current)
        return True

    async def source_is_current(self, snapshot) -> bool:
        return snapshot.current(self)

    def _complete_latest(
        self, snapshot: HistorySourceSnapshot, request: LatestViewportRequest,
    ) -> None:
        if snapshot.current(self):
            request.restore(snapshot.window)
            request.destination.source_settled(snapshot.window)
            snapshot.window.lookahead.destination_complete()

    def paging_window(self):
        # What an edge check decides from: the saved extent, the pages'
        # loaded ranges and the filter. A check that finds a read running is
        # skipped, and the read asks again only when one of these changed
        # under it, so a filter chosen during a read must count.
        return self.page_source.through, self.filter, tuple(
            (page.prepared.page.before, page.prepared.page.after, page.prepared.capture_range()) for page in self.pages)

    def rows_published(self) -> None:
        """Admit source rows and withdraw their live predecessors before yielding."""
        self._source_state.rows_published(self)
        for page in self.pages:
            page.display = True

    def source_failed(self, error) -> None:
        self.retire_source()
        self.app.show_error(error, "History")

    def prepare_viewport(self) -> None:
        """Consume committed geometry once, on this source's own pump."""
        if self.can_draw_on_screen:
            self.latest = self.latest.resume(self)
            self.prepare_visible_pages()
            self.state.check_edges(self)

    def invalidate_projection(self) -> None:
        self._generation += 1

    def supersede_source_work(
        self, operation: WorkingTranscript, request: LatestViewportRequest,
    ) -> None:
        """Replace an edge read with End's destination without publishing it."""
        if self._source_state is not operation:
            return
        self._source_observation.close()
        self._source_state = operation.source
        self.cancel_work()
        request.apply(self)

    def retire_source(self, *, parked: bool = False) -> Awaitable[None]:
        """Withdraw publication now; join its cancelled work independently."""
        self._source_observation.close()
        source = self._source_state.retirement_source()
        self._source_state = (ParkedSourceTranscript(source) if parked
                              else RetiredSourceTranscript(source))
        self._generation += 1
        if self.is_attached:
            self.window.histories.discard(self)
        self._source_state.retire_preparation(self)
        return self.joined(self.cancel_work())

    def finish_source_work(self, operation: WorkingTranscript) -> None:
        # Only the current operation may publish. A cancelled
        # old operation cannot publish again or settle a newer source's work.
        if self._source_state is operation:
            self._source_observation.close()
            self._source_state = operation.source
            if self.state.can_draw:
                self.window.check_follow()
                # The admitted operation owns source and reader progress.
                # Native compensation and unchanged reads cannot rearm it.
                if operation.progressed(self):
                    self.request_preparation()
                self.latest.prepare(self)
                self.publish_core(TranscriptSourceWorkFinished())
                if all(history.state.accepts_source_work for history in self.window.histories):
                    self.window.reader_position.source_settled(self.window)
            # Work handed over while this held the source; what arrives while it runs is owed
            # to that operation in turn, so a burst's last revision is always read.
            for work in tuple(operation.owed.values()):
                self.schedule_source_work(work)

    def resume_source(self) -> None:
        self._source_state = self._source_state.resume()
        self.followed_here()
        self.source_resumed()
        self.window.check_follow()
        self.request_preparation()

    @property
    def fragments(self) -> tuple[HistoryFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.prepared.fragments)

    @property
    def fragment_limit(self) -> int:
        # Screen rows are not fragment counts: one prepared fragment may contain
        # a dozen lines or a whole indivisible Markdown block. Grow with the
        # number actually visible, keeping two loaded batches in reserve.
        return max(self._fragment_budget, self._visible_fragment_budget())

    def _visible_fragment_budget(self) -> int:
        return self.budget.item_limit(len(self.visible_fragments()))

    @property
    def fragment_count(self) -> int:
        return sum(page.prepared.stop - page.prepared.start for page in self.pages)

    def load_initial_page(self) -> None:
        self.request_latest(LatestPosition.hold(self.window))

    async def _page_added(self, page: TranscriptPage, fragments: tuple[HistoryFragment, ...]) -> None:
        """A page joined what this history draws."""

    def extend_source(self, through: TranscriptCursor) -> None:
        """The source now reaches `through`; the drawn pages stay as they are."""
        self._generation += 1
        self.page_source.through = through
        edge = self.pages[-1]
        edge.prepared.page = replace(edge.prepared.page, has_newer=edge.prepared.page.after != through)
        self._update_edges()

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        """A saved viewer or nested pager shows every category; a conversation's history shows its filter."""
        return all_categories()

    # How a restricted category selection shows: Textual reads and mounts a projection
    # (`SeekingFilter`), Qt draws only the selected rows of the pages it holds (`DrawnFilter`).
    # Each frontend's history names its `toad.transcript_filter.FilterState` member.
    restricted_filter: ClassVar[type]

    @property
    def drawn_extent(self) -> tuple[int, int]:
        """The rows the loaded pages draw and the messages behind them, each page measured once."""
        drawn = tuple((rows, page) for page in self.pages if (rows := page.line_count))
        return (sum(rows for rows, _page in drawn),
                sum(page.prepared.stop - page.prepared.start for _rows, page in drawn))

    @property
    def draws_rows(self) -> bool:
        """Whether the loaded range draws anything: the first page that does answers, with no sum
        over the rest. Asked on every scrolled frame, so its cost must not grow with history."""
        return any(page.line_count for page in self.pages)

    @property
    def drawn_tail_followed(self) -> bool:
        return not self.drawn_end_more and self.follows_source_tail

    async def _load_page(
        self, end: PageEnd,
        publication_current: Callable[[], bool] = lambda: True,
    ) -> bool:
        """Publish one readable range; report whether its edge still needs rows."""
        snapshot = self.source_snapshot()
        window = snapshot.window
        # Only an append beyond the fully drawn, followed end is an arrival.
        # Local range growth, older paging and destination restoration are not.
        followed_end = end.fresh(self)

        def current() -> bool:
            if not snapshot.current(self) or not publication_current():
                return False
            return window.follows_tail if followed_end else window.lookahead.demand.accepts_result(end)

        try:
            if not current():
                return False
            edge = end.edge(self.pages)
            page_range = edge.prepared.capture_range()
            edge_cursor = edge.prepared.page.before, edge.prepared.page.after
            demand = window.lookahead.demand
            missing = (window.lookahead.ahead_rows(window.viewport_rows) if followed_end
                       else window.lookahead.read_rows(self, end))
            local = end.can_extend(edge.prepared)
            if local:
                staged = edge.prepared.for_view()
            else:
                source = self.page_source
                if not source.has_more(end, edge.prepared.page):
                    return False
                staged = await source.get(end.adjacent(edge.prepared.page))
                demand.source_read()
                if (not await self.source_is_current(snapshot) or not current()
                        or not await source.accept_page(self, edge, staged)):
                    return False
            # Speculation warms the same scoped runtime entry as the next
            # foreground request; it does not copy decoded pages into a widget.
            window.lookahead.demand.prepare_ahead(window.lookahead, self, staged.page, end)
            await staged.prepare_rows(
                self, current, target=self, selected=self.selected_categories, end=end,
                boundary=end.edge_boundary(edge, local, staged),
                rows_needed=max(1, missing), limit=self.fragment_limit)
            if not current():
                return False
            async with window.history_lock:
                if not current():
                    return False
                if end.edge(self.pages) is not edge:
                    return False
                if edge.prepared.capture_range() != page_range:
                    return False
                protected = {fragment.key for fragment in self.visible_fragments()}
                async with window.preserve_history():
                    arrivals = self._source_state.arriving(staged, followed_end)
                    await self._extend_and_trim(edge, end, local, protected, staged, current=current)
                    self._require_can_draw()
                    self.window.arrivals_followed(arrivals)
                    self.hold_arrival(arrivals)
                    self.repaint(arrivals)
                    self.rows_published()
                    if not local:
                        await self._page_added(staged.page, staged.fragments)
            self.state.delivered(self)
            advanced = end.edge(self.pages)
            if (advanced is edge and edge.prepared.capture_range() == page_range
                    and (edge.prepared.page.before, edge.prepared.page.after) == edge_cursor):
                return False
            if followed_end or not current():
                return False
            return bool(window.lookahead.read_rows(self, end))
        except _DrawingStopped:
            return False
        finally:
            if self.state.can_draw:
                self.window.check_follow()

    async def _extend_and_trim(
        self, edge: DrawnPage, end: PageEnd, local: bool,
        protected: set[FragmentKey], prepared: PreparedTranscriptPage, *,
        current: Callable[[], bool],
    ) -> None:
        """Load the next range and trim fragments the reader is not seeing.

        protected holds ids of fragments that must stay loaded: the visible
        ones and those just loaded for the reader's direction of travel.
        """
        async with self.lock:
            previous_start = self.pages[0], self.pages[0].prepared.start
            overlay_visible = bool(self.filter.overlay.visible_fragments())
            protected_pages: set[DrawnPage] = set()
            if not prepared.fragments:
                # A nonmatching interval advances the original source span,
                # not the native tree. No empty page widget or decoded cache.
                end.advance_empty(edge.prepared, prepared)
            elif local:
                previous = {fragment.key for fragment in edge.prepared.fragments_in_range}
                if not await edge.prepared.extend(edge, prepared, current):
                    raise _DrawingStopped
                self._require_can_draw()
                protected.update(fragment.key for fragment in edge.prepared.fragments_in_range
                                 if fragment.key not in previous)
            else:
                page_range = edge.prepared.capture_range()
                async with self.page_view_type.acquire(
                    self, prepared, end=end, pages=self.pages,
                    current=lambda: current() and edge.prepared.capture_range() == page_range,
                ) as view:
                    end.append(self.pages, view)
                protected.update(fragment.key for fragment in view.prepared.fragments_in_range)
                protected_pages.add(view)
            self._fragment_budget = limit = max(
                self.budget.item_limit(len(protected)), self._visible_fragment_budget(),
            )
            excess = self.fragment_count - limit
            while (excess > 0 or len(self.pages) > limit) and (self.fragment_count > 1 or len(self.pages) > 1):
                for side in end.eviction_order(self):
                    # A visible older projection protects the range between it
                    # and the main pages, just like a visible page.
                    if not side.can_evict(overlay_visible):
                        continue
                    evicted = side.edge(self.pages)
                    if evicted in protected_pages:
                        continue
                    members = tuple(side.eviction_fragments(evicted.prepared))
                    available = 0
                    for fragment in members:
                        if fragment.key in protected:
                            break
                        available += 1
                    if available or not members:
                        break
                else:
                    # No side has a page it may evict.
                    break
                count = evicted.prepared.stop - evicted.prepared.start
                remove_count = min(max(0, excess), available, self.fragment_count - 1)
                if remove_count >= count and len(self.pages) > 1:
                    side.pop(self.pages)
                    evicted.remove()
                    excess -= count
                else:
                    if not remove_count:
                        break
                    side.trim(evicted, min(remove_count, count))
                    excess -= remove_count
            self.filter.canonical_moved(previous_start, overlay_visible)
            self._update_edges()




class OffScreenRunway:
    """A history the screen does not show: nothing is read ahead for it."""

    on_screen: ClassVar[bool] = False

    def read_rows(self, preparation: DirectionalPreparation, history: HistoryPager, end: PageEnd) -> int:
        return 0


@dataclass(frozen=True)
class Runway(OffScreenRunway):
    """Published rows of one history above and below the viewport."""

    on_screen = True
    above: int
    below: int

    def read_rows(self, preparation: DirectionalPreparation, history: HistoryPager, end: PageEnd) -> int:
        # Fill a visible hole even without scroll input; only the demand
        # predicts rows beyond that already-visible need.
        missing = min(preparation.window.unfilled_rows, -end.rows_toward(self))
        return max(0, missing, preparation.demand.read_rows(preparation, history, end, self))


class PreparationDemand(ABC):
    """One scroll intent; its cases own prediction and incoming travel."""

    @abstractmethod
    def rows(self, horizon: float) -> float: ...

    def moved(self, travel: float, elapsed: float) -> PreparationDemand:
        return MovingPreparation(travel, elapsed)

    def accepts_result(self, end: PageEnd) -> bool:
        """A running read may finish after input settles; it starts no next read."""
        return True

    def read_rows(
        self, preparation: DirectionalPreparation, history: HistoryPager, end: PageEnd, runway: Runway,
    ) -> int:
        """Stationary input never requests another source page."""
        return 0

    def source_read(self) -> None:
        """Only a bounded destination counts the pages its request read."""

    def prepare_ahead(self, preparation: DirectionalPreparation, history: HistoryPager, page, end: PageEnd) -> None:
        """Only measured movement speculates beyond its current destination."""

    def destination_painted(self) -> PreparationDemand:
        return self


class StationaryPreparation(PreparationDemand):
    def rows(self, horizon: float) -> float:
        return 0


@dataclass
class MovingPreparation(PreparationDemand):
    """One gesture's measured travel: its accumulated rows over its accumulated time.

    Terminal input arrives in clumps (several wheel reports in one read), so the gap
    between two reports says nothing about speed; the gesture's whole distance over
    its whole duration does, however the reports were batched.
    """

    travel: float
    seconds: float

    @property
    def velocity(self) -> float:
        return self.travel / self.seconds

    def moved(self, travel: float, elapsed: float) -> PreparationDemand:
        if self.travel * travel > 0:
            # Continue measuring this direction; reversal starts a new demand.
            self.travel += travel
            self.seconds += elapsed
            return self
        return super().moved(travel, elapsed)

    def rows(self, horizon: float) -> float:
        return self.velocity * horizon

    def accepts_result(self, end: PageEnd) -> bool:
        return end.accepts_velocity(self.velocity)

    def read_rows(self, preparation: DirectionalPreparation, history: HistoryPager, end: PageEnd, runway: Runway) -> int:
        if not self.accepts_result(end):
            return 0
        ahead = preparation.ahead_rows(preparation.window.viewport_rows)
        return max(0, ceil(ahead) - end.rows_toward(runway))

    def prepare_ahead(self, preparation: DirectionalPreparation, history, page, end: PageEnd) -> None:
        if self.accepts_result(end):
            history.read_ahead(partial(history.page_source.prepare_next, page, end))


@dataclass
class DestinationPreparation(PreparationDemand):
    target_rows: int
    pages_read: int = 0

    def rows(self, horizon: float) -> float:
        return self.target_rows

    def moved(self, travel: float, elapsed: float) -> PreparationDemand:
        # End's own destination layout is not an intermediate scroll demand.
        # An explicit reversal immediately replaces the burst.
        return super().moved(travel, elapsed) if travel < 0 else self

    def accepts_result(self, end: PageEnd) -> bool:
        # A newer destination supersedes older work through its source snapshot.
        return end.accepts_destination

    def read_rows(self, preparation: DirectionalPreparation, history: HistoryPager, end: PageEnd, runway: Runway) -> int:
        if not self.accepts_result(end):
            return 0
        edge = end.edge(history.pages).prepared
        if not end.can_extend(edge) and not preparation.budget.can_read_destination(self.pages_read):
            return 0
        return max(0, self.target_rows - history.drawn_extent[0])

    def source_read(self) -> None:
        self.pages_read += 1

    def destination_painted(self) -> PreparationDemand:
        return StationaryPreparation()


class DirectionalPreparation:
    """Measured travel during preparation, owned by the existing viewport.

    Idle expiry measures input cadence, not a renderer's frame rate. Measured
    accepted source and foreground body delivery supply the prediction horizon,
    including source reads, worker waits and native widget construction.
    The presentation budget bounds how much of that prediction can be retained.
    """

    def __init__(self, window: PagingWindow) -> None:
        self.window = window
        self.position = 0.0
        self.sampled_at = monotonic()
        self.delivery_seconds = 0.0
        self.demand: PreparationDemand = StationaryPreparation()

    @property
    def budget(self) -> PresentationBudget:
        return self.window.presentation_budget

    def observe(self, position: float) -> bool:
        travel = position - self.position
        if travel:
            self._moved(travel)
            self.position = position
        return bool(travel)

    def requested(self, travel: float) -> None:
        """Measure reader input whose lazy edge has no native travel yet."""
        self._moved(travel)

    def request_boundary(self, travel: float) -> bool:
        """Measure reader input while its lazy source edge has no native travel."""
        window = self.window
        end = OLDER_END if travel < 0 else NEWER_END
        if not end.at_boundary(window) or not any(end.visible_more(h) for h in window.histories):
            return False
        self.requested(travel)
        window._schedule_settle()
        end.leave_tail(window)
        window.request_preparation()
        return True

    def _moved(self, travel: float) -> None:
        now = monotonic()
        elapsed = min(
            self.idle_seconds,
            max(now - self.sampled_at, get_clock_info("monotonic").resolution),
        )
        self.demand = self.demand.moved(travel, elapsed)
        self.sampled_at = now

    def relocated(self, compensation: float) -> None:
        """Translate measured travel by the applied reader compensation.

        Restoration is geometry compensation, not another input sample. Keep
        the existing demand's velocity, direction and expiry unchanged.
        """
        self.position += compensation

    def settle(self) -> None:
        self.demand = StationaryPreparation()
        self.delivery_seconds = 0.0

    def destination(self, rows: int, *, pages_read: int = 0) -> None:
        self.demand = DestinationPreparation(self.budget.runway_rows(rows), pages_read)
        self.sampled_at = monotonic()

    def destination_complete(self) -> None:
        """The bottom viewport painted; ordinary idle runway may resume."""
        self.demand = self.demand.destination_painted()
        self.delivery_seconds = 0.0

    def delivered(self, seconds: float) -> None:
        self.delivery_seconds = seconds

    @property
    def idle_seconds(self) -> float:
        return self.budget.scroll_idle_seconds

    @property
    def travel_rows(self) -> float:
        elapsed = monotonic() - self.sampled_at
        if elapsed >= self.idle_seconds:
            return 0
        return self.demand.rows(max(self.budget.lookahead_seconds,
                                   self.delivery_seconds * self.budget.delivery_safety_factor))

    def ahead_rows(self, viewport_rows: int) -> int:
        # Travel is a demand, not a native retention limit. The existing worker
        # and presentation owners independently bound its prepared resources.
        destination = self.window.animated_travel
        baseline = self.budget.runway_rows(viewport_rows)
        return max(baseline, ceil(abs(self.travel_rows)), ceil(abs(destination)))

    def destination_batch(self, budget: PresentationBudget, viewport_rows: int) -> int:
        # A bottom viewport must be complete before its one tree publication.
        # One selected fragment supplies at least one drawn row; visible
        # destination items may exceed the nominal working-set item budget.
        return max(budget.item_limit(0), viewport_rows)

    def read_rows(self, history: HistoryPager, end: PageEnd) -> int:
        if not end.visible_more(history):
            return 0
        return self.runway(history).read_rows(self, history, end)

    def runway(self, history: HistoryPager) -> OffScreenRunway:
        """Published rows above and below this viewport, or that the history is off screen."""
        return self.window.runway(history)

    def prepare_source(self, history: HistoryPager) -> None:
        """Request the next page from what the screen shows now, not from window state."""
        window = self.window
        if (not window.presenting or not history.selected_categories
                or not self.runway(history).on_screen):
            return
        if history.follows_source_tail and NEWER_END.visible_more(history):
            window.jump_to_latest()
        elif not history.draws_rows and NEWER_END.visible_more(history):
            # A filter can hide the whole loaded range. Ask the ordinary
            # source owner for the next range, not an invented row at its end.
            history.request_page(NEWER_END)
        elif history.filter.active:
            # Projection scans share the original source's decoded boundary.
            history.filter.check_edges()
        else:
            for end in (OLDER_END, NEWER_END):
                if self.read_rows(history, end):
                    history.request_page(end)
                    return

    def request_older(self) -> None:
        """An explicit earlier-history control is demand, even without travel."""
        window = self.window
        self.requested(-max(1, window.content_rows))
        window._schedule_settle()
        window.request_preparation()


class NativePresentation:
    """Native resource costs and requirements; the default owns no resources."""

    @property
    def retained_widget_count(self) -> int:
        return 0

    @property
    def retained_source_bytes(self) -> int:
        return 0

    @property
    def retained_paint_bytes(self) -> int:
        return 0

    def required_presentations(self, screen) -> tuple[NativePresentation, ...]:
        """Resources whose actual native identity must survive this budget pass."""
        return ()


class ConversationPager(HistoryPager):
    """A conversation's pager: it can replace its whole source with a newer reading of it."""

    async def show_newest(self, request: ReplacementViewportRequest, *,
                          arrivals: tuple[HistoryFragment, ...] = (),
                          publication_current: Callable[[], bool] = lambda: True) -> bool:
        """Replace the drawn source, retaining the followed tail's active arrivals."""
        retained = (tuple(fragment for page in self.pages for fragment in page.prepared.fragments_in_range
                          if fragment.key in page.arrivals)
                    if self.follows_source_tail else ())
        self._generation += 1
        published = await self.jump_latest(request, publication_current)
        if published:
            self.window.arrivals_followed(arrivals)
            self.repaint(arrivals, continuing=retained)
        return published


class NativePager:
    """What the toolkit's own history base answers for the pager: listed after that base,
    so its members answer first. Textual's Widget and CoreEventReceiver supply these."""

    lock: asyncio.Lock

    @abstractmethod
    def repaint(self, fragments: tuple[HistoryFragment, ...] = (), *, continuing=()) -> None:
        """Draw these fragments' rows again (Textual's history animates them in)."""

    @property
    @abstractmethod
    def is_attached(self) -> bool: ...

    @property
    @abstractmethod
    def is_leaving(self) -> bool:
        """Whether the history is being taken down: its source states stop drawing."""

    @abstractmethod
    def run_worker(self, work: Callable[[], Awaitable[object]], **options: object) -> object:
        """Run source work off the caller; the handle's wait() joins it."""

    @abstractmethod
    def call_after_refresh(self, callback: Callable, *arguments: object) -> object:
        """Call back once the next frame is drawn."""

    @abstractmethod
    async def remove_children(self, pages: tuple[DrawnPage, ...]) -> None:
        """Retire page views the pager no longer draws."""

    @abstractmethod
    def publish_core(self, event: object) -> None:
        """Tell the history's listeners its source work finished."""


class DrawsBusMessages:
    """The fragments the loaded pages draw, and whether they include a bus message, scrolled into view or not."""

    pages: deque[DrawnPage]

    @property
    def fragments_in_range(self) -> tuple[HistoryFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.prepared.fragments_in_range)

    def draws(self, reference: MessageReference) -> bool:
        return any(fragment.draws(reference) for fragment in reversed(self.fragments_in_range))
