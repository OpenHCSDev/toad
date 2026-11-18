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
from toad.client.sort_control import ChannelListOrder, CommsSortWrite, SortControlBase
from python_introspect import FieldLabel
from textual.geometry import Region
from textual.widget import Widget
from textual.widgets import Static
from toad.widget_actions import Activates

from toad.widgets.comms_menu import ContextMenu
from formbridge.forms.declared_fields import FieldPath, Placeholder
from toad.setting_declarations import FamilyChoices
from textual.events import Mount
from textual import on


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


class SortChoice[Order: DisplayOrder](SortControlBase[Order]):
    """One ordering choice and its anchored Textual menu.

    `SortControlBase` owns the toolkit-neutral form + order + label/tooltip state;
    this subclass adds the Textual-specific menu (`open_sort`), writer glue and
    the `sort_host`/`sort_anchor` hooks a Textual presenter supplies. Qt renders
    the same state through its own subclass (`QtChannelSortControl`)."""

    @property
    @abstractmethod
    def sort_host(self) -> Widget:
        """The widget presenting this choice: its app, screen and workers run the menu."""

    @property
    @abstractmethod
    def sort_anchor(self) -> Region:
        """Where the presenter shows this choice; the menu opens under it."""

    async def open_sort(self) -> None:
        """Open the choice's menu under its anchor."""
        host = self.sort_host
        form = self.form
        if form is None:
            host.notify("Ordering is not available yet", title="Sort", severity="warning")
            return
        write = await self.order_writer()

        choices = form.choices
        orders = tuple(choices.choices())
        items = [(partial(self._choose_order, order, write), choices.label(order))
                 for order in orders]
        for path in self.visibility_fields():
            field = path.bind(host.app.saved_settings.state)
            items.append((partial(self._toggle_visibility, path),
                          f"{'✓' if field.value else '○'} {field.label}"))

        def choose(action):
            if action:
                action()

        menu = ContextMenu.show(host.screen, self.sort_anchor, "Sort", items, callback=choose)
        for index, order in enumerate(orders):
            if order is self.order:
                menu.options.highlighted = index

    def _choose_order(self, order: type[Order],
                      write: Callable[[type[Order]], Awaitable[object]]) -> None:
        if order is not self.order:
            # Only the backend observation updates the displayed order.
            self.sort_host.run_worker(write(order), group="sort-order")

    def _toggle_visibility(self, path: FieldPath) -> None:
        settings = self.sort_host.app.saved_settings
        settings.toggle(path)
        self.sort_host.run_worker(settings.save(), group="channel-visibility")

    def visibility_fields(self) -> tuple[FieldPath, ...]:
        return ()

    @abstractmethod
    async def order_writer(self) -> Callable[[type[Order]], Awaitable[object]]: ...


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

    @on(Mount)
    def on_mount(self):
        self.sort_changed()

    def sort_changed(self) -> None:
        if self.content != (label := self.sort_label):
            self.update(label)
        if self.tooltip != (tooltip := self.sort_tooltip):
            self.tooltip = tooltip

    @property
    def sort_host(self) -> Widget:
        return self

    @property
    def sort_anchor(self) -> Region:
        return self.region

    async def activate(self):
        await self.open_sort()


class CommsSortChoice[Order: DisplayOrder](CommsSortWrite[Order], SortChoice[Order]):
    """Both channel controls write through the Core that supplies their observed rows; each
    names the request its own order is stored by (`CommsSortWrite`)."""

    async def order_writer(self) -> Callable[[type[Order]], Awaitable[object]]:
        host = self.sort_host
        access = host.app.coordination_access
        observed = await access.preparation.run_thread(access.observation.observed)
        return partial(self.write_order, observed, access, host.screen.coordination_root)


class ChannelListSort(ChannelListOrder, CommsSortChoice[ChannelSort], SortControl[ChannelSort]):
    def __init__(self):
        super().__init__(ChannelSortForm, "channels")
