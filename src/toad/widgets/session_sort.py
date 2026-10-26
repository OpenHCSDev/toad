"""Anchored menus edit Core ordering choices; observed rows own their result."""

from __future__ import annotations

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
from python_introspect import FieldLabel, declared_annotation_choices
from textual import events
from textual.widgets import Static
from textual._activation import PrimaryActivation
from textual.geometry import Offset

from toad.forms.field_path import FieldPath, declared_annotation
from toad.widgets.comms_menu import ContextMenu
from toad.forms.kinds import Placeholder
from toad.preferences import SETTINGS
from toad.setting_declarations import FamilyChoices


@dataclass(frozen=True)
class ThreadSortForm:
    placeholder: ClassVar[Placeholder] = Placeholder("Mixed orders")
    order: Annotated[
        type[ThreadSort] | None, FamilyChoices(ThreadSort), FieldLabel("Member order"), placeholder
    ]


@dataclass(frozen=True)
class ChannelSortForm:
    placeholder: ClassVar[Placeholder] = Placeholder("Choose order")
    order: Annotated[
        type[ChannelSort] | None, FamilyChoices(ChannelSort), FieldLabel("Channel order"), placeholder
    ]


class SortControl[Order: DisplayOrder](InlineSelection, PrimaryActivation, Static, can_focus=True):
    highlight_foreground = ForegroundColour

    BINDINGS = [("enter,space", "choose_sort", "Sort")]
    DEFAULT_CSS = """
    SortControl {
        width: auto;
        max-width: 60%;
        height: 1;
        margin-left: 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
        color: $text-muted;
        pointer: pointer;
    }
    """

    def __init__(self, form_type: type[ThreadSortForm] | type[ChannelSortForm], scope: str):
        super().__init__()
        self.scope = scope
        self.form_type = form_type
        self.form: ThreadSortForm | ChannelSortForm | None = None

    @property
    def order(self) -> type[Order] | None:
        return self.form.order if self.form is not None else None

    def update_order(self, order: type[Order] | None) -> None:
        if self.form is None or order is not self.order:
            self.form = self.form_type(order)
            self._update_label()

    def on_mount(self):
        self._update_label()

    def _update_label(self) -> None:
        order = self.order
        text = (order.label() if order is not None else
                self.form.placeholder.text if self.form is not None else "Sort")
        label = f"{text} ▾"
        tooltip = (f"Sort {self.scope} by {order.label().lower()}" if order is not None
                   else f"Choose how to sort {self.scope}")
        if self.content != label:
            self.update(label)
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    @property
    def primary_activation(self):
        return self.action_choose_sort

    async def action_choose_sort(self):
        form = self.form
        if form is None:
            self.notify("Ordering is not available yet", title="Sort", severity="warning")
            return
        write = await self.order_writer()

        choices = declared_annotation_choices(declared_annotation(FieldPath(type(form)).order))
        assert choices is not None
        orders = tuple(choices.choices())
        items = [(partial(self._choose_order, order, write), choices.label(order))
                 for order in orders]
        for path in self.visibility_fields():
            field = path.bind(self.app.saved_settings.state)
            items.append((partial(self._toggle_visibility, path),
                          f"{'✓' if field.value else '○'} {field.label}"))

        def choose(action):
            if action is not None:
                action()

        menu = ContextMenu.show(
            self.screen, Offset(self.region.x, self.region.bottom), "Sort", items,
            callback=choose,
        )
        if self.order is not None:
            menu.options.highlighted = orders.index(self.order)

    def _choose_order(self, order: type[Order], write: Callable[[type[Order]], Awaitable[object]]) -> None:
        if order is not self.order:
            # Only the backend observation updates the displayed order.
            self.run_worker(write(order), group="sort-order")

    def _toggle_visibility(self, path: FieldPath) -> None:
        settings = self.app.saved_settings
        settings.toggle(path)
        self.run_worker(settings.save(), group="channel-visibility")

    def visibility_fields(self) -> tuple[FieldPath, ...]:
        return ()

    @abstractmethod
    async def order_writer(self) -> Callable[[type[Order]], Awaitable[object]]: ...

    async def on_click(self, event: events.Click):
        event.stop()
        if event.button == 1:
            await self.action_choose_sort()


class CommsSortControl[Order: DisplayOrder](SortControl[Order]):
    """Both channel controls write through the route that supplies their observed rows."""

    def __init__(self, form_type: type[ThreadSortForm] | type[ChannelSortForm], scope: str, *, channel: str | None = None):
        self.channel = channel
        super().__init__(form_type, scope)

    async def order_writer(self) -> Callable[[type[Order]], Awaitable[object]]:
        access = self.app.coordination_access
        observed = await access.preparation.run_thread(access.observation.observed)
        return partial(observed.write_order, access, self.screen.coordination_root, self.channel)


class SessionSort(CommsSortControl[ThreadSort]):
    def __init__(self, channel: str):
        super().__init__(ThreadSortForm, channel, channel=channel)


class ChannelListSort(CommsSortControl[ChannelSort]):
    def __init__(self):
        super().__init__(ChannelSortForm, "channels")

    def visibility_fields(self) -> tuple[FieldPath, ...]:
        return SETTINGS.sidebar.show_stopped, SETTINGS.sidebar.show_archived
