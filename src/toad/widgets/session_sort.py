"""Forms edit typed Core ordering choices; the sidebar only displays their result."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from agent_comms.display_order import (
    ChannelSort, CreatedThreadSort, DisplayOrder, NameChannelSort, ThreadSort,
)
from objectstate import ObjectState
from python_introspect import FieldLabel
from textual import events
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from toad.forms.field_path import FieldPath
from toad.forms.form_view import FormView
from toad.preferences import SETTINGS
from toad.setting_choices import FamilyChoices


@dataclass(frozen=True)
class ThreadSortForm:
    order: Annotated[
        type[ThreadSort] | None, FamilyChoices(ThreadSort), FieldLabel("Member order")
    ] = CreatedThreadSort


@dataclass(frozen=True)
class ChannelSortForm:
    order: Annotated[
        type[ChannelSort], FamilyChoices(ChannelSort), FieldLabel("Channel order")
    ] = NameChannelSort


class SortDialog(ModalScreen[type[DisplayOrder] | None]):
    """A short-lived edit form, not a second source of persisted ordering."""

    BINDINGS = [("escape", "cancel", "Close")]

    def __init__(self, control: SortControl):
        super().__init__()
        self.control = control
        self.state = ObjectState(control.form_type(control.order))
        self.form = FormView(self.state)
        self.visibility = control.visibility_fields()
        self.visibility_form = (FormView(self.app.saved_settings.state, paths=self.visibility)
                                if self.visibility else None)

    def compose(self):
        with VerticalScroll() as panel:
            panel.styles.width = 52
            panel.styles.max_width = "90%"
            panel.styles.height = "auto"
            panel.styles.max_height = "90vh"
            panel.styles.padding = (1, 2)
            yield Static(f"Sort {self.control.scope}")
            self.form.styles.height = "auto"
            yield self.form
            if self.visibility_form is not None:
                self.visibility_form.styles.height = "auto"
                yield self.visibility_form

    def on_mount(self):
        self.styles.align = ("center", "middle")
        self.state.on_resolved_changed(self.order_changed)
        self.call_after_refresh(self.focus_next)

    def order_changed(self, paths: set[str]):
        if "order" in paths:
            order = self.state.get_resolved_value("order")
            if order is not None and order is not self.control.order:
                self.dismiss(order)

    def on_unmount(self):
        self.state.off_resolved_changed(self.order_changed)
        if self.visibility:
            self.app.run_worker(self.app.saved_settings.save(), group="channel-visibility")

    def action_cancel(self):
        self.dismiss(None)


class SortControl[Order: DisplayOrder](Static, can_focus=True):
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
    SortControl:hover, SortControl:focus { color: $text; text-style: underline; }
    """

    def __init__(self, form: ThreadSortForm | ChannelSortForm, scope: str):
        super().__init__()
        self.scope = scope
        self.order = form.order
        self.form_type = type(form)

    def update_order(self, order: type[Order] | None) -> None:
        if order is not self.order:
            self.order = order
            self._update_label()

    def on_mount(self):
        self._update_label()

    def _update_label(self) -> None:
        order = self.order
        label = f"{order.label()} ▾" if order is not None else "Sort ▾"
        tooltip = (f"Sort {self.scope} by {order.label().lower()}" if order is not None
                   else f"Sort {self.scope} (currently different orders)")
        if self.content != label:
            self.update(label)
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    def action_choose_sort(self):
        try:
            write = self.order_writer()
        except (OSError, ValueError) as error:
            self.notify(str(error), title="Sort", severity="error")
            return

        def choose(order):
            if order is not None:
                self.run_worker(self._save_order(order, write), group="sort-order")

        self.app.push_screen(SortDialog(self), choose)

    def visibility_fields(self) -> tuple[FieldPath, ...]:
        return ()

    async def _save_order(self, order: type[Order], write: Callable[[type[Order]], Awaitable[object]]) -> None:
        try:
            await write(order)
            # Only the backend observation updates the displayed order.
        except (OSError, ValueError) as error:
            self.notify(str(error), title="Sort", severity="error")

    @abstractmethod
    def order_writer(self) -> Callable[[type[Order]], Awaitable[object]]: ...

    def on_click(self, event: events.Click):
        event.stop()
        if event.button == 1:
            self.action_choose_sort()


class CommsSortControl[Order: DisplayOrder](SortControl[Order]):
    """Both channel controls write through the route that supplies their observed rows."""

    def order_writer(self) -> Callable[[type[Order]], Awaitable[object]]:
        access = self.app.coordination_access
        observed = access.observation
        if observed is None:
            raise ValueError("Comms ordering is not available yet")
        source_root = self.screen.coordination_root
        if source_root is not None and observed.selection.root != Path(source_root).resolve():
            raise ValueError("Comms route changed before sorting")
        async def write(order):
            return await self.app.preparation.run_thread(
                access.write, observed.selection, self.store_order, observed.service.channels, order,
            )

        return write

    @abstractmethod
    def store_order(self, channels, order: type[Order]) -> type[Order]: ...


class SessionSort(CommsSortControl[ThreadSort]):
    def __init__(self, channel: str):
        self.channel = channel
        super().__init__(ThreadSortForm(), channel)

    def store_order(self, channels, order: type[ThreadSort]) -> type[ThreadSort]:
        return channels.set_channel_sort(self.channel, order).order


class ChannelListSort(CommsSortControl[ChannelSort]):
    def __init__(self):
        super().__init__(ChannelSortForm(), "channels")

    def store_order(self, channels, order: type[ChannelSort]) -> type[ChannelSort]:
        return channels.set_channel_order(order)

    def visibility_fields(self) -> tuple[FieldPath, ...]:
        return SETTINGS.sidebar.show_stopped, SETTINGS.sidebar.show_archived
