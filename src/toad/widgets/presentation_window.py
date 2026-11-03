"""Shared budgets for a source-backed window of native widget presentation."""

from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields, replace
from functools import partial
from itertools import zip_longest
from math import ceil
from operator import ge, gt
from time import get_clock_info, monotonic
from typing import TYPE_CHECKING, Annotated, ClassVar, get_args

from agent_comms.message_page import PageBounds
from agent_comms.transcripts import TranscriptCursor
from textual.geometry import Region
from textual.screen import Screen
from toad.work_preparation import WorkRevision

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent_comms.message_page import MessagePage
    from agent_comms.transcripts import TranscriptPage
    from agent_comms.ui_model.message_category import MessageCategory
    from textual.widget import Widget

    from toad.transcript_preparation import (
        PreparedTranscriptPage,
        ProjectedTranscriptSource,
    )
    from toad.transcript_source_preparation import TranscriptSourcePreparation
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_history import LineHistory, TranscriptPageView
    from toad.wire_history import AfterSequence, WireCut, WireSource


def protected_presentations(items: Iterable["Widget"], endpoints: Iterable["Widget"]) -> set["Widget"]:
    """Resolve native selection/focus to its owning presentation, without geometry."""
    from textual.widget import Widget

    candidates = set(items)
    protected = set()
    for endpoint in endpoints:
        node = endpoint
        while isinstance(node, Widget):
            if node in candidates:
                protected.add(node)
                break
            node = node.parent
    return protected


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

    def required_presentations(self, screen: Screen) -> tuple[NativePresentation, ...]:
        """Resources whose actual native identity must survive this budget pass."""
        return ()


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
        return [owner for pair in zip_longest(before, after)
                for owner in pair if owner is not None]


class OffScreenRunway:
    """A history the screen does not show: nothing is read ahead for it."""

    on_screen: ClassVar[bool] = False

    def read_rows(self, preparation: DirectionalPreparation, history: LineHistory, end: PageEnd) -> int:
        return 0


@dataclass(frozen=True)
class Runway(OffScreenRunway):
    """Published rows of one history above and below the viewport."""

    on_screen = True
    above: int
    below: int

    def read_rows(self, preparation: DirectionalPreparation, history: LineHistory, end: PageEnd) -> int:
        window = preparation.window
        viewport = window.scrollable_size
        occupied = window.arrange(viewport).flow_bounds
        # Native virtual size includes the viewport's blank alignment space.
        # Flowing placements retain the actual occupied extent, excluding
        # overlays and docks. Fill a visible hole even without scroll input;
        # only the demand predicts rows beyond that already-visible need.
        missing = min(viewport.height - occupied.height, -end.rows_toward(self))
        return max(0, missing, preparation.demand.read_rows(preparation, history, end, self))


class Unplaced:
    """A widget Textual's map has no entry for: the screen does not show it."""

    def shown_region(self) -> Region | None:
        """Where the screen shows the widget; None is the block cursor's answer for a widget it cannot show."""
        return None

    def rows_region(self, rows: range) -> Region | None:
        """Where the screen shows some of the widget's rows, as the block cursor answers it."""
        return None

    def shows_from(self, row: int, top: int) -> bool:
        """Whether the widget's `row` is drawn at or below screen row `top`."""
        return False

    def head_hidden(self, row: int, window: HistoryWindow, height: int) -> bool:
        """Whether a message of this height starting at the widget's `row` needs its head placed.
        Where an unshown row is is unknown, so only the height decides."""
        return window.message_too_tall(height)

    def under[Found](self, rows: PointerRows[Found], y: int) -> Found:
        """What the widget draws at screen row `y`."""
        return rows.unshown()

    def runway(self, viewport: Unplaced) -> OffScreenRunway:
        """This widget's rows above and below `viewport`."""
        return OffScreenRunway()

    def runway_of(self, region: Region) -> OffScreenRunway:
        """As the viewport: the rows of a widget at `region` above and below it."""
        return OffScreenRunway()

    def overlaps(self, region: Region) -> bool:
        return False

    def shows(self, region: Region, clip: Region) -> bool:
        """As the viewport: whether a widget at `region`, clipped to `clip`, is in view."""
        return False


UNPLACED = Unplaced()


@dataclass(frozen=True)
class Placed(Unplaced):
    """Where the screen shows the widget, including the part scrolled out of view."""

    region: Region

    def shown_region(self) -> Region | None:
        return self.region

    def rows_region(self, rows: range) -> Region | None:
        region = self.region
        return Region(region.x, region.y + rows.start, region.width, len(rows))

    def shows_from(self, row: int, top: int) -> bool:
        return self.region.y + row >= top

    def head_hidden(self, row: int, window: HistoryWindow, height: int) -> bool:
        return window.message_head_hidden(height, self.region.y + row)

    def under[Found](self, rows: PointerRows[Found], y: int) -> Found:
        return rows.shown_row(y - self.region.y)

    def runway(self, viewport: Unplaced) -> OffScreenRunway:
        return viewport.runway_of(self.region)

    def runway_of(self, region: Region) -> OffScreenRunway:
        frame = self.region
        return Runway(frame.y - region.y, region.bottom - frame.bottom) if region.overlaps(frame) else OffScreenRunway()

    def overlaps(self, region: Region) -> bool:
        return region.overlaps(self.region)

    def shows(self, region: Region, clip: Region) -> bool:
        viewport = self.region
        return region.overlaps(viewport) and region.overlaps(clip) and clip.overlaps(viewport)


class PointerRows[Found]:
    """A widget that answers what it draws at one of its rows, or that it is not shown.
    A mixin beside Widget, so it declares its methods without ABC's metaclass."""

    @abstractmethod
    def shown_row(self, row: int) -> Found: ...

    @abstractmethod
    def unshown(self) -> Found: ...


def arranged(widget: Widget) -> Unplaced:
    """Where the screen's arranged map shows a widget: the one read of that Textual map."""
    geometry = widget.screen._compositor.visible_widgets.get(widget)
    return UNPLACED if geometry is None else Placed(geometry[0])


class PageEnd(ABC):
    """One end owns page traversal, source reads and eviction at that edge."""

    step: ClassVar[int]
    accepts_destination = True

    def boundary(self, page: PreparedTranscriptPage) -> int:
        return self.entry(len(page.fragments) + 1)

    def indices(self, page: PreparedTranscriptPage, boundary: int) -> range:
        return range(boundary + min(self.step, 0), self.edge((-1, len(page.fragments))), self.step)

    def can_extend(self, page: PreparedTranscriptPage) -> bool:
        return self.edge((page.start, len(page.fragments) - page.stop)) > 0

    def has_more(self, through, page) -> bool:
        return self.edge((page.has_older, page.has_newer))

    def adjacent(self, page) -> PageRequest:
        return PageRequest(self, self.edge((page.before, page.after)))
    @abstractmethod
    def advance_empty(self, edge: PreparedTranscriptPage, staged: PreparedTranscriptPage) -> None: ...
    @abstractmethod
    def edge[Item](self, pages: Sequence[Item]) -> Item: ...
    def edge_boundary(self, edge: TranscriptPageView, local: bool, staged: PreparedTranscriptPage) -> int:
        return self.edge((edge.prepared.start, edge.prepared.stop)) if local else self.boundary(staged)
    @abstractmethod
    async def mount(self, history: LineHistory, view: TranscriptPageView, pages: deque[TranscriptPageView]) -> None: ...
    @staticmethod
    @abstractmethod
    def append[Item](pages: deque[Item], view: Item, /) -> None: ...
    @staticmethod
    @abstractmethod
    def pop[Item](pages: deque[Item], /) -> Item: ...

    def eviction_fragments(self, page: PreparedTranscriptPage):
        return page.fragments_in_range[:: -self.step]
    def rows_toward(self, runway: Runway) -> int:
        return self.edge((runway.above, runway.below))
    def at_boundary(self, window: HistoryWindow) -> bool:
        boundary = self.edge((0, window.max_scroll_y))
        return all((position - boundary) * self.step >= 0
                   for position in (window.scroll_y, window.scroll_target_y))

    @abstractmethod
    def work_revision[Cursor](self, request: "PageRequest[Cursor]", through: Cursor) -> WorkRevision: ...
    @abstractmethod
    async def load_page(self, loader, cursor: TranscriptCursor, through) -> TranscriptPage: ...
    def progressed(self, page: "TranscriptPage", cursor: TranscriptCursor) -> bool:
        edge = self.edge((page.before, page.after))
        start, stop = self.edge(((edge, cursor), (cursor, edge)))
        return cursor.accepts_source(edge) and not (
            start.contains(stop) and self.edge((page.has_older, page.has_newer)))
    @abstractmethod
    def wire_page(self, source: WireSource, cursor: WireCut, through: AfterSequence) -> MessagePage: ...

    def entry(self, length: int):
        return self.edge((length - 1, 0))

    async def project(
        self, source: ProjectedTranscriptSource, initial: PreparedTranscriptPage, prepared: PreparedTranscriptPage,
    ):
        return replace(prepared, page=replace(prepared.page, has_newer=True))

    def visible_more(self, history: TranscriptSourcePreparation):
        return history.has_more(self)

    def fresh(self, history: LineHistory) -> bool:
        return False

    def accepts_velocity(self, velocity: float) -> bool:
        return velocity * self.step > 0

    async def walk(
        self, history: LineHistory, current: Callable[[], bool], target,
        selected: frozenset[type[MessageCategory]], start: tuple[int, int], rows_needed: int, limit: int,
    ):
        for index in range(start[0], self.edge((-1, len(history.pages))), self.step):
            if not current() or rows_needed <= 0 or limit <= 0:
                break
            page = history.pages[index].prepared
            boundary = start[1] if index == start[0] else self.boundary(page)
            rows_needed -= await page.prepare_rows(
                history, current, target=target, selected=selected, end=self,
                boundary=boundary, rows_needed=rows_needed, limit=limit)
            limit -= page.stop - page.start
        return rows_needed, limit

    def eviction_order(self, history: TranscriptSourcePreparation) -> tuple[PageEnd, PageEnd]:
        return OLDER_END, NEWER_END

    def can_evict(self, overlay_visible: bool) -> bool:
        return True

    def leave_tail(self, window: HistoryWindow) -> None:
        pass

    def trim(self, view: TranscriptPageView, count: int) -> None:
        page = view.prepared
        page.set_fragment_range(slice(page.start + self.edge((count, 0)), page.stop - self.edge((0, count))))
        view.range_changed()


class OlderEnd(PageEnd):
    def work_revision[Cursor](self, request: "PageRequest[Cursor]", through: Cursor) -> WorkRevision:
        return PageRevision(request)

    step = -1
    pop = staticmethod(deque.popleft)
    append = staticmethod(deque.appendleft)

    async def load_page(self, loader, cursor, through) -> TranscriptPage:
        return await through.read_page(loader, cursor.earlier_page())

    def wire_page(self, source: WireSource, cursor: WireCut, through: AfterSequence) -> MessagePage:
        return source.conversation.page(source, PageBounds(
            cursor.older(),
            source.tail_limit if cursor == through else source.page_limit))

    def advance_empty(self, edge: PreparedTranscriptPage, staged: PreparedTranscriptPage) -> None:
        edge.page = replace(edge.page, before=staged.page.before, has_older=staged.page.has_older)

    def edge[Item](self, pages: Sequence[Item]) -> Item:
        return pages[0]

    async def mount(self, history: LineHistory, view: TranscriptPageView, pages: deque[TranscriptPageView]) -> None:
        await history.mount(view, before=self.edge(pages) if pages else history.newer)

    def eviction_order(self, history: TranscriptSourcePreparation) -> tuple[PageEnd, PageEnd]:
        return super().eviction_order(history) if history.follows_source_tail else (NEWER_END, self)

    def can_evict(self, overlay_visible: bool) -> bool:
        return not overlay_visible

    def leave_tail(self, window: HistoryWindow) -> None:
        window.release_anchor()


class NewerEnd(PageEnd):
    def work_revision[Cursor](self, request: "PageRequest[Cursor]", through: Cursor) -> WorkRevision:
        return GrowingPageRevision(request, through)

    step = 1
    accepts_destination = False
    pop = staticmethod(deque.pop)
    append = staticmethod(deque.append)

    def has_more(self, through, page):
        return super().has_more(through, page) or page.after != through

    async def load_page(self, loader, cursor, through) -> TranscriptPage:
        return await through.read_page(loader, cursor.later_page())

    def wire_page(self, source: WireSource, cursor: WireCut, through: AfterSequence) -> MessagePage:
        page = source.conversation.page(source, PageBounds(cursor.newer(), source.page_limit))
        kept = tuple(message for message in page.messages if message.view_key[0] or message.seq <= through.cursor.sequence)
        return replace(page, messages=kept, has_newer=False) if len(kept) < len(page.messages) else page

    async def project(
        self, source: ProjectedTranscriptSource, initial: PreparedTranscriptPage, prepared: PreparedTranscriptPage,
    ):
        if not prepared.fragments and not prepared.page.has_newer:
            boundary = await source.boundary()
            return replace(boundary, page=replace(boundary.page, before=initial.page.before,
                                                 has_older=initial.page.has_older))
        return await super().project(source, initial, prepared)

    def advance_empty(self, edge: PreparedTranscriptPage, staged: PreparedTranscriptPage) -> None:
        edge.page = replace(edge.page, after=staged.page.after, has_newer=staged.page.has_newer)

    def fresh(self, history: LineHistory):
        return history.drawn_tail_followed

    def edge[Item](self, pages: Sequence[Item]) -> Item:
        return pages[-1]

    async def mount(self, history: LineHistory, view: TranscriptPageView, pages: deque[TranscriptPageView]) -> None:
        await history.mount(view, before=history.newer)


OLDER_END = OlderEnd()
NEWER_END = NewerEnd()


@dataclass(frozen=True)
class PageRequest[Cursor = TranscriptCursor]:
    end: PageEnd
    cursor: Cursor

    def progressed(self: PageRequest[TranscriptCursor], page: "TranscriptPage") -> bool:
        return self.end.progressed(page, self.cursor)


@dataclass(frozen=True)
class PageRevision[Cursor = TranscriptCursor](WorkRevision):
    """An older request is bounded by its own cursor, independent of new arrivals."""

    request: PageRequest[Cursor]
    size: ClassVar[int] = 512


@dataclass(frozen=True)
class GrowingPageRevision[Cursor = TranscriptCursor](PageRevision[Cursor]):
    """A newer request also depends on the frontier this read reached."""

    through: Cursor


class PreparationDemand(ABC):
    """One scroll intent; its cases own prediction and incoming travel."""

    @abstractmethod
    def rows(self, horizon: float) -> float: ...

    def moved(self, travel: float, elapsed: float) -> "PreparationDemand":
        return MovingPreparation(travel, elapsed)

    def accepts_result(self, end: PageEnd) -> bool:
        """A running read may finish after input settles; it starts no next read."""
        return True

    def read_rows(
        self, preparation: "DirectionalPreparation", history: LineHistory, end: PageEnd, runway: Runway,
    ) -> int:
        """Stationary input never requests another source page."""
        return 0

    def source_read(self) -> None:
        """Only a bounded destination counts the pages its request read."""

    def prepare_ahead(self, preparation: DirectionalPreparation, history: LineHistory, page, end: PageEnd) -> None:
        """Only measured movement speculates beyond its current destination."""

    def destination_painted(self) -> "PreparationDemand":
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

    def read_rows(self, preparation: DirectionalPreparation, history: LineHistory, end: PageEnd, runway: Runway) -> int:
        if not self.accepts_result(end):
            return 0
        ahead = preparation.ahead_rows(preparation.window.outer_size.height)
        return max(0, ceil(ahead) - end.rows_toward(runway))

    def prepare_ahead(self, preparation: DirectionalPreparation, history, page, end: PageEnd) -> None:
        if self.accepts_result(end):
            # The existing runtime owns the single decoded/prepared result.
            # This native worker only waits for that original bounded work;
            # foreground paging shares it, without a page store in the widget.
            history.run_worker(partial(history.page_source.prepare_next, page, end),
                               group="transcript-read-ahead", exclusive=True,
                               exit_on_error=False)


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

    def read_rows(self, preparation: DirectionalPreparation, history: LineHistory, end: PageEnd, runway: Runway) -> int:
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

    def __init__(self, window: HistoryWindow) -> None:
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
        window = self.window
        destination = (window.scroll_target_y - window.scroll_y
                       if window.app.animator.is_being_animated(window, "scroll_y") else 0)
        baseline = self.budget.runway_rows(viewport_rows)
        return max(baseline, ceil(abs(self.travel_rows)), ceil(abs(destination)))

    def destination_batch(self, budget: PresentationBudget, viewport_rows: int) -> int:
        # A bottom viewport must be complete before its one tree publication.
        # One selected fragment supplies at least one drawn row; visible
        # destination items may exceed the nominal working-set item budget.
        return max(budget.item_limit(0), viewport_rows)

    def read_rows(self, history: LineHistory, end: PageEnd) -> int:
        if not end.visible_more(history):
            return 0
        return self.runway(history).read_rows(self, history, end)

    def runway(self, history: LineHistory) -> OffScreenRunway:
        """Published rows above and below this viewport, or that the history is off screen."""
        return arranged(history).runway(arranged(self.window))

    def prepare_source(self, history: LineHistory) -> None:
        """Request the next page from what the screen shows now, not from window state."""
        window = self.window
        if (not window.screen.is_active or not history.selected_categories
                or not self.runway(history).on_screen):
            return
        if history.follows_source_tail and NEWER_END.visible_more(history):
            window.jump_to_latest()
        elif not history.drawn_extent[0] and NEWER_END.visible_more(history):
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
        self.requested(-max(1, window.scrollable_content_region.height))
        window._schedule_settle()
        window.request_preparation()
