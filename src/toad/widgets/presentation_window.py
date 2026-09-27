"""Shared budgets for a source-backed window of native widget presentation."""

from dataclasses import dataclass
from collections.abc import Iterable

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
    reserve_batches: int = 2
    minimum_widgets: int = 300
    widgets_per_row: int = 10

    def __post_init__(self) -> None:
        for name in ("max_items", "admission_items", "minimum_widgets"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("reserve_batches", "widgets_per_row"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    def item_limit(self, protected_items: int) -> int:
        return max(self.max_items, protected_items + self.reserve_batches * self.admission_items)

    def widget_limit(self, viewport_rows: int) -> int:
        return max(self.minimum_widgets, viewport_rows * self.widgets_per_row)
