"""Forms edit typed Core ordering choices; the sidebar only displays their result."""

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
from objectstate import ObjectState
from python_introspect import FieldLabel
from textual import events
from textual.containers import VerticalScroll
from textual.widgets import Static
from textual._activation import PrimaryActivation
from textual.css.scalar import Scalar, Unit
from textual.geometry import Spacing

from toad.forms.field_path import FieldPath
from toad.forms.form_view import InlineFormView
from toad.forms.presentation import FormModal
from toad.widget_view import WidgetView
from toad.forms.kinds import Placeholder
from toad.preferences import SETTINGS
from toad.setting_choices import FamilyChoices


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


class SortPanel(WidgetView, VerticalScroll):
    width = Scalar.from_number(52)
    max_width = Scalar(90, Unit.PERCENT, Unit.WIDTH)
    max_height = Scalar(90, Unit.VIEW_HEIGHT, Unit.VIEW_HEIGHT)
    padding = Spacing(1, 2, 1, 2)
    overflow_y = "auto"


class SortDialog(FormModal[type[DisplayOrder] | None]):
    """A short-lived edit form, not a second source of persisted ordering."""

    def __init__(self, control: SortControl, form: ThreadSortForm | ChannelSortForm):
        super().__init__()
        self.control = control
        self.state = ObjectState(form)
        self.order_field = FieldPath(type(form)).order.bind(self.state)
        self.form = InlineFormView(self.state, focus=self.order_field.path)
        paths = control.visibility_fields()
        self.visibility_form = (InlineFormView(self.app.saved_settings.state, paths=paths)
                                if paths else None)

    def compose(self):
        with SortPanel():
            yield Static(f"Sort {self.control.scope}")
            yield self.form
            if self.visibility_form is not None:
                yield self.visibility_form

    def on_mount(self):
        self.state.on_resolved_changed(self.order_changed)

    def order_changed(self, paths: set[str]):
        if self.order_field.path.value in paths:
            order = self.order_field.value
            if order is not None and order is not self.control.order:
                self.dismiss(order)

    def on_unmount(self):
        self.state.off_resolved_changed(self.order_changed)
        if self.visibility_form is not None:
            self.app.run_worker(self.app.saved_settings.save(), group="channel-visibility")


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

    def action_choose_sort(self):
        form = self.form
        if form is None:
            self.notify("Ordering is not available yet", title="Sort", severity="warning")
            return
        try:
            write = self.order_writer()
        except (OSError, ValueError) as error:
            self.notify(str(error), title="Sort", severity="error")
            return

        def choose(order):
            if order is not None:
                self.run_worker(self._save_order(order, write), group="sort-order")

        self.app.push_screen(SortDialog(self, form), choose)

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

    def __init__(self, form_type: type[ThreadSortForm] | type[ChannelSortForm], scope: str, *, channel: str | None = None):
        self.channel = channel
        super().__init__(form_type, scope)

    def order_writer(self) -> Callable[[type[Order]], Awaitable[object]]:
        access = self.app.coordination_access
        return partial(access.observation.write_order, access, self.screen.coordination_root, self.channel)


class SessionSort(CommsSortControl[ThreadSort]):
    def __init__(self, channel: str):
        super().__init__(ThreadSortForm, channel, channel=channel)


class ChannelListSort(CommsSortControl[ChannelSort]):
    def __init__(self):
        super().__init__(ChannelSortForm, "channels")

    def visibility_fields(self) -> tuple[FieldPath, ...]:
        return SETTINGS.sidebar.show_stopped, SETTINGS.sidebar.show_archived
