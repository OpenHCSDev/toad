"""Shared budgets for a source-backed window of native widget presentation."""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, fields
from functools import partial
from math import ceil
from operator import ge, gt
from time import get_clock_info, monotonic
from typing import TYPE_CHECKING, Annotated, ClassVar, get_args

from textual.geometry import Region
from textual.screen import Screen
from textual.widget import Widget

from toad.client.history_preparation import NEWER_END, OLDER_END, PageEnd

if TYPE_CHECKING:
    from collections.abc import Callable

    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_history import LineHistory


def protected_presentations(items: Iterable[Widget], endpoints: Iterable[Widget]) -> set[Widget]:
    """Resolve native selection/focus to its owning presentation, without geometry."""
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
        # Nearest first on both sides; a side that has run out contributes nothing.
        return [owner for index in range(max(len(before), len(after)))
                for owner in (*before[index:index + 1], *after[index:index + 1])]


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

    @staticmethod
    def found[Entry](entry: Entry | None, region: Callable[[Entry], Region]) -> Unplaced:
        """The one decoder of a Textual compositor map's entry: none means the screen does not show it."""
        return UNPLACED if entry is None else Placed(region(entry))

    def shown_rows(self, rows: range) -> Unplaced:
        """Where the screen shows some of the widget's rows: nowhere."""
        return self

    def top(self, default: int) -> int:
        """The screen row the widget starts at, or `default` when it is not shown."""
        return default

    def rows_within(self, origin: int, height: int) -> range:
        """The rows of a strip starting at screen row `origin` that the widget covers."""
        return range(0)

    def reveal_clicked(self, window: HistoryWindow) -> None:
        """A click cannot land on a widget the screen does not show."""

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

    def regions(self) -> tuple[Region, ...]:
        """The screen regions the widget is shown in."""
        return ()


UNPLACED = Unplaced()


@dataclass(frozen=True)
class Placed(Unplaced):
    """Where the screen shows the widget, including the part scrolled out of view."""

    region: Region

    def regions(self) -> tuple[Region, ...]:
        return (self.region,)

    def shown_rows(self, rows: range) -> Placed:
        region = self.region
        return Placed(Region(region.x, region.y + rows.start, region.width, len(rows)))

    def top(self, default: int) -> int:
        return self.region.y

    def rows_within(self, origin: int, height: int) -> range:
        return range(max(0, self.region.y - origin), min(height, self.region.bottom - origin))

    def reveal_clicked(self, window: HistoryWindow) -> None:
        """Scroll a clicked message whose head is above the viewport to its head."""
        region = self.region
        if window.message_head_hidden(region.height, region.y):
            window.release_anchor()
            window.scroll_relative(
                y=region.y - window.scrollable_content_region.y,
                animate=False, immediate=True,
            )

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
    return Unplaced.found(widget.screen._compositor.visible_widgets.get(widget), lambda geometry: geometry[0])
















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
        self, preparation: DirectionalPreparation, history: LineHistory, end: PageEnd, runway: Runway,
    ) -> int:
        """Stationary input never requests another source page."""
        return 0

    def source_read(self) -> None:
        """Only a bounded destination counts the pages its request read."""

    def prepare_ahead(self, preparation: DirectionalPreparation, history: LineHistory, page, end: PageEnd) -> None:
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
