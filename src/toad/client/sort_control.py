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

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, ClassVar

from agent_comms.display_order import ChannelSort, ThreadSort
from formbridge.forms.declared_fields import Placeholder
from python_introspect import FieldLabel

from toad.preferences import SETTINGS
from toad.setting_declarations import FamilyChoices

if TYPE_CHECKING:
    from agent_comms.display_order import DisplayOrder
    from formbridge.forms.declared_fields import FieldPath
    from agent_comms.transport.request import ToolRequest


@dataclass(frozen=True)
class ThreadSortForm:
    """A thread list's sort form, for every frontend: its order's choices and placeholder."""

    choices: ClassVar[FamilyChoices] = FamilyChoices(ThreadSort)
    placeholder: ClassVar[Placeholder] = Placeholder("Mixed orders")
    order: Annotated[
        type[ThreadSort] | None, choices, FieldLabel("Member order"), placeholder
    ]


@dataclass(frozen=True)
class ChannelSortForm:
    """The channel list's sort form, for every frontend."""

    choices: ClassVar[FamilyChoices] = FamilyChoices(ChannelSort)
    placeholder: ClassVar[Placeholder] = Placeholder("Choose order")
    order: Annotated[
        type[ChannelSort] | None, choices, FieldLabel("Channel order"), placeholder
    ]


SortForm = ThreadSortForm | ChannelSortForm
SortFormType = type[ThreadSortForm] | type[ChannelSortForm]


class CommsSortWrite[Order: "DisplayOrder"]:
    """A sort control whose order the Core stores: each names the request its order is
    stored by, and the write goes through the observed Core. Textual's `CommsSortChoice`
    and Qt's `QtSortControl` both inherit it."""

    @abstractmethod
    def order_request(self, order: "type[Order]") -> "ToolRequest": ...

    async def write_order(self, observed, access, root, order: "type[Order]") -> object:
        return await observed.write_order(access, root, self.order_request(order))


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


class ChannelListOrder(CommsSortWrite["ChannelSort"]):
    """The Channels panel header's order: the channel list's order, stored by
    `CommsSortChannelsTool`, with the stopped/archived filters beside it in its menu.
    Textual's `ChannelListSort` and Qt's `QtChannelListSort` both inherit it."""

    def order_request(self, order: "type[ChannelSort]") -> "ToolRequest":
        from agent_comms.transport.tools.sidebar import CommsSortChannelsTool
        return CommsSortChannelsTool(order=order)

    def visibility_fields(self) -> "tuple[FieldPath, ...]":
        return SETTINGS.sidebar.show_stopped, SETTINGS.sidebar.show_archived


class ChannelMemberOrder(CommsSortWrite["ThreadSort"]):
    """One channel's member order, stored by `CommsSortChannelTool` under the channel's name
    (the control's scope). Textual's `ChannelSortChoice` and Qt's `QtChannelSortControl`
    both inherit it."""

    scope: str

    def order_request(self, order: "type[ThreadSort]") -> "ToolRequest":
        from agent_comms.transport.tools.sidebar import CommsSortChannelTool
        return CommsSortChannelTool(name=self.scope, order=order)


class RelationshipOrder(SortControlBase["ThreadSort"]):
    """A thread's relationship groups' order: Textual's `RelationshipSort` and Qt's
    `QtRelationshipSort` both inherit it. The label shows the one order every sortable group
    shares (none when they differ), and a pick writes it to each group."""

    def update_groups(self, groups) -> None:
        orders = {group.order for group in groups}
        self.update_order(next(iter(orders)) if len(orders) == 1 else None)

    @staticmethod
    async def write_relationship_order(preparation, service, identity, groups, order) -> None:
        for group in groups:
            await preparation.run_thread(
                service.set_relationship_order, identity.thread_name(), type(group), order)
