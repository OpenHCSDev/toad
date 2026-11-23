"""Textual's native sidebar widget binding over the shared `SidebarStateMachine`."""

from __future__ import annotations

from metaclass_registry.mro_dispatch import handles
from textual import (
    events,
    on,
)
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from toad.app_node import ToadNode
from toad.client.connection import FailedObservation
from toad.client.sidebar_lines import SidebarStatusLine
from toad.client.sidebar_state import (
    EMPTY,
    Behind,
    BoundSidebar,
    Current,
    Detached,
    FailedSidebarState,
    SidebarModelState,
    SidebarStateMachine,
)
from toad.core.events import ThreadRowStateChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.sidebar_changes import ChangedThreads


class SidebarStatus(SidebarStatusLine, Static):
    """The sidebar's status line (the shared `SidebarStatusLine`): its title, then the detail
    indented under it, as Qt's `StatusSection` draws it."""

    def show_status(self, text: str) -> None:
        title, detail = self.status_rows(text)
        self.update(f"{title}\n{self.detail_text(detail)}" if detail else title)


class SidebarModelView(SidebarStateMachine, CoreEventReceiver, ToadNode, Widget):
    """A widget showing the observed service's sidebar model.

    Core's model is observed only while a view shows it. Changes that arrive
    while this one is hidden are applied in one pass when it shows again.
    """

    def __init__(self, *args: Widget, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.unavailable = SidebarStatus("", markup=False)

    model_state: reactive[SidebarModelState] = reactive(Detached, repaint=False, always_update=True)

    @on(events.Mount)
    async def on_mount(self) -> None:
        await self.mount(self.unavailable)
        self.watch_model_state(self.model_state)
        self.observe_core(self.app.events)
        self.observe_core(self.app.coordination_access.events)
        await self.app.coordination_access.follow_sidebar(self)

    @on(events.Unmount)
    def on_unmount(self) -> None:
        self.stop_showing()

    @on(events.Show)
    def on_show(self) -> None:
        self.present()

    def sidebar_visibility_changed(self) -> None:
        self.present()

    def watch_model_state(self, state: SidebarModelState) -> None:
        for child in self.children:
            child.display = state.shows_child(self, child)

    def coordination_access(self):
        return self.app.coordination_access

    def show_status(self, text: str) -> None:
        self.unavailable.show_status(text)

    def hide_status(self) -> None:
        # Textual keeps unavailable's visibility under watch_model_state via shows_child; the
        # state's own transition is what hides or shows it, so there is nothing to do here.
        return

    def bind_failed_observation(self, observed: FailedObservation) -> None:
        super().bind_failed_observation(observed)
        self.display = True

    @handles(ThreadRowStateChanged)
    async def thread_row_state_changed(self, event: ThreadRowStateChanged) -> None:
        """Repaint only the thread rows named by the app event."""
        self.present(change=ChangedThreads(event.names))
