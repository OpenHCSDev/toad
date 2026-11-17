"""Toolkit-neutral sort-control state.

`SortControlBase[Order]` owns the current form (order + choices + placeholder) and
the polymorphic `update_order` / `sort_label` / `sort_tooltip` answers both
frontends share. Textual's `SortChoice` (widgets/session_sort.py) inherits it and
layers menu-opening + writer behaviour on top; Qt's `QtChannelSortControl`
(toad/qt/channel_sort.py) inherits it and renders through QToolButton + QMenu.

Pattern: the state owner lives here; each frontend attaches its own rendering.
Mirrors the `SidebarFilter` (PR #1972) and `PanelSpec` (PR #1984) hoists —
one authority per concept, two renderings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_comms.display_order import DisplayOrder
    from toad.widgets.session_sort import ChannelSortForm, ThreadSortForm

    SortForm = ThreadSortForm | ChannelSortForm
    SortFormType = type[ThreadSortForm] | type[ChannelSortForm]


class SortControlBase[Order: "DisplayOrder"]:
    """State owner for an ordering choice; both frontends inherit and render.

    Holds the current `form` (the `ThreadSortForm`/`ChannelSortForm` the Textual
    form machinery instantiates per order), the `scope` text used in the tooltip,
    and the `form_type` constructor. `update_order` rebuilds the form when the
    order changes and calls the `sort_changed` hook so renderers repaint.

    `sort_label` and `sort_tooltip` are toolkit-neutral read helpers both
    renderings use directly.
    """

    def __init__(
        self,
        form_type: "SortFormType",
        scope: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.scope = scope
        self.form_type = form_type
        self.form: "SortForm | None" = None

    @property
    def order(self) -> "type[Order] | None":
        return self.form.order if self.form is not None else None

    def update_order(self, order: "type[Order] | None") -> None:
        """Rebuild the form when the chosen order changes; call `sort_changed`
        so the renderer repaints its label/tooltip."""
        if self.form is None or order is not self.order:
            self.form = self.form_type(order)
            self.sort_changed()

    def sort_changed(self) -> None:
        """Hook for renderers to repaint their display after `update_order`.
        Default is a no-op; subclasses override."""

    @property
    def sort_label(self) -> str:
        order = self.order
        text = (
            order.label() if order is not None
            else self.form.placeholder.text if self.form is not None
            else "Sort"
        )
        return f"{text} ▾"

    @property
    def sort_tooltip(self) -> str:
        order = self.order
        return (
            f"Sort {self.scope} by {order.label().lower()}" if order is not None
            else f"Choose how to sort {self.scope}"
        )
