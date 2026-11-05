"""Anchored menus edit Core ordering choices; observed rows own their result."""

from __future__ import annotations

from toad.native_style import (
    AutoWidth,
    EllipsisOverflow,
    MutedText,
    NoWrap,
    OneRow,
    PointerCursor,
)
from toad.widgets.selection import InlineSelection
from ui_theme.scheme import ForegroundColour

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import Annotated, ClassVar

from agent_comms.display_order import (
    ChannelSort, DisplayOrder, ThreadSort,
)
from agent_comms.tools import CommsSortChannelTool, CommsSortChannelsTool
from python_introspect import FieldLabel
from textual.geometry import Region
from textual.widget import Widget
from textual.widgets import Static
from toad.widget_actions import Activates

from toad.widgets.comms_menu import ContextMenu
from formbridge.forms.declared_fields import FieldPath, Placeholder
from toad.preferences import SETTINGS
from toad.setting_declarations import FamilyChoices
from agent_comms.tool_request import ToolRequest
from toad.comms_root import CoordinationAccess, Observing


@dataclass(frozen=True)
class ThreadSortForm:
    choices: ClassVar[FamilyChoices] = FamilyChoices(ThreadSort)
    placeholder: ClassVar[Placeholder] = Placeholder("Mixed orders")
    order: Annotated[
        type[ThreadSort] | None, choices, FieldLabel("Member order"), placeholder
    ]


@dataclass(frozen=True)
class ChannelSortForm:
    choices: ClassVar[FamilyChoices] = FamilyChoices(ChannelSort)
    placeholder: ClassVar[Placeholder] = Placeholder("Choose order")
    order: Annotated[
        type[ChannelSort] | None, choices, FieldLabel("Channel order"), placeholder
    ]


class SortChoice[Order: DisplayOrder]:
    """One ordering choice and its anchored menu. A widget or a header segment presents it."""

    def __init__(self, form_type: type[ThreadSortForm] | type[ChannelSortForm], scope: str, **kwargs):
        super().__init__(**kwargs)
        self.scope = scope
        self.form_type = form_type
        self.form: ThreadSortForm | ChannelSortForm | None = None

    @property
    def order(self) -> type[Order] | None:
        return self.form.order if self.form is not None else None

    def update_order(self, order: type[Order] | None) -> None:
        if self.form is None or order is not self.order:
            self.form = self.form_type(order)
            self.sort_changed()

    def sort_changed(self) -> None:
        """The presenter repaints what sort_label and sort_tooltip now answer."""

    @property
    def sort_label(self) -> str:
        order = self.order
        text = (order.label() if order is not None else
                self.form.placeholder.text if self.form is not None else "Sort")
        return f"{text} ▾"

    @property
    def sort_tooltip(self) -> str:
        order = self.order
        return (f"Sort {self.scope} by {order.label().lower()}" if order is not None
                else f"Choose how to sort {self.scope}")

    async def open_sort(self, host: Widget, region: Region) -> None:
        """Open the choice's menu under `region`, in `host`'s screen."""
        form = self.form
        if form is None:
            host.notify("Ordering is not available yet", title="Sort", severity="warning")
            return
        write = await self.order_writer(host)

        choices = form.choices
        orders = tuple(choices.choices())
        items = [(partial(self._choose_order, host, order, write), choices.label(order))
                 for order in orders]
        for path in self.visibility_fields():
            field = path.bind(host.app.saved_settings.state)
            items.append((partial(self._toggle_visibility, host, path),
                          f"{'✓' if field.value else '○'} {field.label}"))

        def choose(action):
            if action:
                action()

        menu = ContextMenu.show(host.screen, region, "Sort", items, callback=choose)
        for index, order in enumerate(orders):
            if order is self.order:
                menu.options.highlighted = index

    def _choose_order(self, host: Widget, order: type[Order],
                      write: Callable[[type[Order]], Awaitable[object]]) -> None:
        if order is not self.order:
            # Only the backend observation updates the displayed order.
            host.run_worker(write(order), group="sort-order")

    def _toggle_visibility(self, host: Widget, path: FieldPath) -> None:
        settings = host.app.saved_settings
        settings.toggle(path)
        host.run_worker(settings.save(), group="channel-visibility")

    def visibility_fields(self) -> tuple[FieldPath, ...]:
        return ()

    @abstractmethod
    async def order_writer(self, host: Widget) -> Callable[[type[Order]], Awaitable[object]]: ...


class SortControl[Order: DisplayOrder](
    SortChoice[Order],
    MutedText,
    AutoWidth,
    OneRow,
    NoWrap,
    EllipsisOverflow,
    PointerCursor,
    InlineSelection,
    Activates,
    Static,
    can_focus=True,
):
    """A sort choice presented as its own control, in a panel header."""

    highlight_foreground = ForegroundColour

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_width = "60%"
        self.styles.margin = (0, 0, 0, 1)

    def on_mount(self):
        self.sort_changed()

    def sort_changed(self) -> None:
        if self.content != (label := self.sort_label):
            self.update(label)
        if self.tooltip != (tooltip := self.sort_tooltip):
            self.tooltip = tooltip

    async def activate(self):
        await self.open_sort(self, self.region)


class CommsSortChoice[Order: DisplayOrder](SortChoice[Order]):
    """Both channel controls write through the Core that supplies their observed rows; each
    names the request its own order is stored by."""

    @abstractmethod
    def order_request(self, order: type[Order]) -> ToolRequest: ...

    async def order_writer(self, host: Widget) -> Callable[[type[Order]], Awaitable[object]]:
        access = host.app.coordination_access
        observed = await access.preparation.run_thread(access.observation.observed)
        return partial(self.write_order, observed, access, host.screen.coordination_root)

    async def write_order(self, observed: Observing, access: CoordinationAccess, root,
                          order: type[Order]) -> object:
        return await observed.write_order(access, root, self.order_request(order))


class ThreadSortChoice(CommsSortChoice[ThreadSort]):
    """A channel's member order, presented by its header line."""

    def __init__(self, channel: str):
        self.channel = channel
        super().__init__(ThreadSortForm, channel)

    def order_request(self, order: type[ThreadSort]) -> CommsSortChannelTool:
        return CommsSortChannelTool(name=self.channel, order=order)


class ChannelListSort(CommsSortChoice[ChannelSort], SortControl[ChannelSort]):
    def __init__(self):
        super().__init__(ChannelSortForm, "channels")

    def order_request(self, order: type[ChannelSort]) -> CommsSortChannelsTool:
        return CommsSortChannelsTool(order=order)

    def visibility_fields(self) -> tuple[FieldPath, ...]:
        return SETTINGS.sidebar.show_stopped, SETTINGS.sidebar.show_archived
