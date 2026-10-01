"""Shared budgets for a source-backed window of native widget presentation."""

from dataclasses import dataclass
from abc import ABC, abstractmethod
from collections.abc import Iterable
from itertools import zip_longest
from math import ceil
from time import monotonic, get_clock_info

from textual.widget import Widget


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


@dataclass(frozen=True)
class PresentationBudget:
    """Tunable working-set policy, not transport-page or source-size limits.

    Visible and explicitly protected items may exceed the nominal item budget.
    Admission remains bounded independently; source data is never discarded to
    satisfy a widget budget.
    """

    max_items: int = 24
    admission_items: int = 4
    reserve_batches: int = 4
    minimum_widgets: int = 300
    widgets_per_row: int = 10
    buffer_viewports: int = 3
    lookahead_seconds: float = 0.3
    scroll_idle_seconds: float = 0.2

    def __post_init__(self) -> None:
        for name in ("max_items", "admission_items", "minimum_widgets", "buffer_viewports"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("reserve_batches", "widgets_per_row"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.lookahead_seconds <= 0 or self.scroll_idle_seconds <= 0:
            raise ValueError("Preparation timing must be positive")

    def item_limit(self, protected_items: int) -> int:
        return max(self.max_items, protected_items + self.reserve_batches * self.admission_items)

    def widget_limit(self, viewport_rows: int) -> int:
        return max(self.minimum_widgets, viewport_rows * self.widgets_per_row)

    def runway_rows(self, viewport_rows: int) -> int:
        return max(1, viewport_rows) * self.buffer_viewports

    def admit(self, candidates, required, viewport_rows: int, max_bytes: int):
        """Visible/protected native bodies first, then ordered bounded resources."""
        admitted = set(required)
        widgets = source_bytes = 0
        for owner in candidates:
            count, size = owner.retained_widget_count, owner.retained_source_bytes
            if owner not in admitted:
                if (widgets + count > self.widget_limit(viewport_rows)
                        or source_bytes + size > max_bytes):
                    continue
                admitted.add(owner)
            widgets += count
            source_bytes += size
        return admitted

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


class PreparationDemand(ABC):
    """One scroll intent; its cases own prediction and incoming travel."""

    @abstractmethod
    def rows(self, horizon: float) -> float: ...

    def moved(self, travel: float, elapsed: float) -> "PreparationDemand":
        return MovingPreparation(travel / elapsed)

    def edges(self, before, after):
        return before, after

    def neighbors(self, sequence, first: int, last: int, count: int):
        return ()

    def body_order(self, runway, predicted):
        return (*runway, *predicted)


class StationaryPreparation(PreparationDemand):
    def rows(self, horizon: float) -> float:
        return 0

    def neighbors(self, sequence, first: int, last: int, count: int):
        # A small idle reserve belongs to the same page/worker resource, not
        # a second cache. Moving demand selects only its incoming direction.
        return (tuple(reversed(sequence[max(0, first - count):first]))
                + tuple(sequence[last:last + count]))


@dataclass
class MovingPreparation(PreparationDemand):
    velocity: float

    def moved(self, travel: float, elapsed: float) -> PreparationDemand:
        velocity = travel / elapsed
        if self.velocity * velocity > 0:
            # This is still the same direction's owned demand. Refresh its
            # measured speed without revoking every admitted batch on each
            # held-key sample. Reversal creates a new demand and revokes it.
            self.velocity = velocity
            return self
        return super().moved(travel, elapsed)

    def rows(self, horizon: float) -> float:
        return self.velocity * horizon

    def neighbors(self, sequence, first: int, last: int, count: int):
        return (tuple(reversed(sequence[max(0, first - count):first]))
                if self.velocity < 0 else tuple(sequence[last:last + count]))

    def body_order(self, runway, predicted):
        # The measured incoming direction gets resource admission first. A
        # reverse runway cannot consume the bound before fast forward travel.
        return (*predicted, *runway)


@dataclass(frozen=True)
class DestinationPreparation(PreparationDemand):
    viewport_rows: int

    def rows(self, horizon: float) -> float:
        return self.viewport_rows

    def moved(self, travel: float, elapsed: float) -> PreparationDemand:
        # End's own destination layout is not an intermediate scroll demand.
        # An explicit reversal immediately replaces the burst.
        return super().moved(travel, elapsed) if travel < 0 else self

    def edges(self, before, after):
        # The existing latest-page operation owns a jump, never edge traversal.
        return None, None


class DirectionalPreparation:
    """Measured travel during preparation, owned by the existing viewport.

    Idle expiry measures input cadence, not a renderer's frame rate. Measured
    foreground body delivery supplies the prediction horizon, including worker
    waits and native widget construction. Speculative worker batches do not
    overwrite that distinct measurement. The existing
    presentation budget bounds how much of that prediction can be admitted.
    """

    def __init__(self, viewport):
        self.viewport = viewport
        self.position = 0.0
        self.sampled_at = monotonic()
        self.delivery_seconds = 0.0
        self.demand: PreparationDemand = StationaryPreparation()

    @property
    def budget(self) -> PresentationBudget:
        return self.viewport.budget

    def observe(self, position: float) -> bool:
        now = monotonic()
        elapsed = now - self.sampled_at
        travel = position - self.position
        if travel:
            elapsed = min(self.idle_seconds, max(elapsed, get_clock_info("monotonic").resolution))
            self.demand = self.demand.moved(travel, elapsed)
            self.sampled_at = now
            self.position = position
        return bool(travel)

    def relocated(self, position: float) -> None:
        """Rebase measured travel after layout preserves the same source reader.

        Restoration is geometry compensation, not another input sample. Keep
        the existing demand's velocity, direction and expiry unchanged.
        """
        self.position = position

    def settle(self) -> None:
        self.demand = StationaryPreparation()

    def destination(self, rows: int) -> None:
        self.demand = DestinationPreparation(rows)
        self.sampled_at = monotonic()

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
        return self.demand.rows(max(self.budget.lookahead_seconds, self.delivery_seconds))

    def ahead_rows(self, viewport_rows: int) -> int:
        # Resource admission still belongs to PresentationBudget / the viewport
        # working set; lookahead cannot ask for an entire skipped transcript.
        return max(self.budget.runway_rows(viewport_rows),
                   ceil(min(viewport_rows * self.budget.reserve_batches, abs(self.travel_rows))))

    def admission(self, budget: PresentationBudget, viewport_rows: int) -> int:
        # Rows and source fragments are different units. Use the original
        # native body's measured extent for both page and body lookahead.
        return min(budget.item_limit(0), max(
            budget.admission_items,
            ceil(self.ahead_rows(viewport_rows) / self.viewport.visible_body_rows),
        ))

    def accepts(self, demand: PreparationDemand) -> bool:
        """Baseline runway survives idle; reversal revokes the original batch."""
        return demand is self.demand
