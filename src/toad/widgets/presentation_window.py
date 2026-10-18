"""Shared budgets for a source-backed window of native widget presentation."""

from dataclasses import dataclass, fields
from abc import ABC, abstractmethod
from collections.abc import Iterable
from itertools import zip_longest
from functools import partial
from math import ceil
from operator import gt, ge
from time import monotonic, get_clock_info
from typing import Annotated, TYPE_CHECKING, get_args

if TYPE_CHECKING:
    from textual.widget import Widget


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

    def fit(self, candidates, required, viewport_rows: int, max_bytes: int):
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


@dataclass(frozen=True)
class Runway:
    """Published rows of one history above and below the viewport."""

    above: int
    below: int



class PreparationDemand(ABC):
    """One scroll intent; its cases own prediction and incoming travel."""

    @abstractmethod
    def rows(self, horizon: float) -> float: ...

    def moved(self, travel: float, elapsed: float) -> "PreparationDemand":
        return MovingPreparation(travel / elapsed)

    def accepts_result(self, end) -> bool:
        """A running read may finish after input settles; it starts no next read."""
        return True

    def read_rows(self, preparation, history, end, runway: Runway) -> int:
        """Stationary input never requests another source page."""
        return 0

    def source_read(self) -> None:
        """Only a bounded destination counts the pages its request read."""

    def prepare_ahead(self, preparation, history, page, end) -> None:
        """Only measured movement speculates beyond its current destination."""

    def destination_painted(self) -> "PreparationDemand":
        return self


class StationaryPreparation(PreparationDemand):
    def rows(self, horizon: float) -> float:
        return 0


@dataclass
class MovingPreparation(PreparationDemand):
    velocity: float

    def moved(self, travel: float, elapsed: float) -> PreparationDemand:
        velocity = travel / elapsed
        if self.velocity * velocity > 0:
            # Continue measuring this direction; reversal starts a new demand.
            self.velocity = velocity
            return self
        return super().moved(travel, elapsed)

    def rows(self, horizon: float) -> float:
        return self.velocity * horizon

    def accepts_result(self, end) -> bool:
        return end.accepts_velocity(self.velocity)

    def read_rows(self, preparation, history, end, runway: Runway) -> int:
        if not self.accepts_result(end):
            return 0
        ahead = preparation.ahead_rows(preparation.window.outer_size.height)
        return max(0, ceil(ahead) - end.rows_toward(runway))

    def prepare_ahead(self, preparation, history, page, end) -> None:
        if self.accepts_result(end):
            # The existing runtime owns the single decoded/prepared result.
            # This native worker only waits for that original bounded work;
            # foreground paging shares it, without a page store in the widget.
            history.run_worker(partial(history._reader().prepare_next, page, end),
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

    def accepts_result(self, end) -> bool:
        # A newer destination supersedes older work through its source snapshot.
        return end.accepts_destination()

    def read_rows(self, preparation, history, end, runway: Runway) -> int:
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

    def __init__(self, window):
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
        from toad.widgets.transcript_history import OlderEnd, NewerEnd
        end = OlderEnd() if travel < 0 else NewerEnd()
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

    def read_rows(self, history, end) -> int:
        if not end.visible_more(history):
            return 0
        runway = self.runway(history)
        return 0 if runway is None else self.demand.read_rows(self, history, end, runway)

    def runway(self, history) -> Runway | None:
        """Published rows above and below this viewport; None while the history is off screen."""
        window = self.window
        visible = window.screen._compositor.visible_widgets
        geometry, viewport = visible.get(history), visible.get(window)
        if geometry is None or viewport is None or not geometry[0].overlaps(viewport[0]):
            return None
        region, frame = geometry[0], viewport[0]
        return Runway(frame.y - region.y, region.bottom - frame.bottom)

    def prepare_source(self, history) -> None:
        """Request the next page from what the screen shows now, not from window state."""
        window = self.window
        if (not window.screen.is_active or not history.selected_categories
                or self.runway(history) is None):
            return
        if history.follows_source_tail and history.has_newer:
            window.jump_to_latest()
        elif history.filter.active:
            # Projection scans share the original source's decoded boundary.
            history.filter.check_edges()
        else:
            from toad.widgets.transcript_history import OlderEnd, NewerEnd
            for end in (OlderEnd(), NewerEnd()):
                if end.read_rows(window, history):
                    history.request_page(end)
                    return

    def request_older(self) -> None:
        """An explicit earlier-history control is demand, even without travel."""
        window = self.window
        self.requested(-max(1, window.scrollable_content_region.height))
        window._schedule_settle()
        window.request_preparation()
