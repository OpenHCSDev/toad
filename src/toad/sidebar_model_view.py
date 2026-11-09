"""A native view's binding to the route's observed sidebar model."""

from __future__ import annotations

from abc import (
    ABC,
    abstractmethod,
)
from dataclasses import dataclass

from agent_comms.messaging.display_references import ReferenceContext
from agent_comms.ui_model.changes import Changes
from agent_comms.ui_model.sidebar import SidebarModel
from metaclass_registry.mro_dispatch import handles
from textual import (
    events,
    on,
)
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from toad.app_node import ToadNode
from toad.comms_root import FailedObservation, Observing
from toad.comms_subscribers import SidebarSubscriber
from toad.core.events import CoordinationObserved, ThreadRowStateChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.sidebar_changes import (
    AllSidebarRows,
    ChangedChannels,
    ChangedThreads,
    SidebarChange,
)

EMPTY = SidebarModel(lambda callback: None)


class SidebarModelState(ABC):
    @abstractmethod
    def shows_child(self, view: SidebarModelView, child: Widget) -> bool:
        """Whether this state's sidebar displays this direct child."""

    def root(self):
        raise RuntimeError("The sidebar has no observed service.")

    @property
    def shown(self) -> SidebarModel:
        return EMPTY

    def shows_model(self) -> bool:
        return False

    def serves(self, path) -> bool:
        return False

    def observes(self, observed: Observing) -> bool:
        return False

    def unsubscribe(self, view: SidebarModelView) -> None:
        pass

    def changes(self, changes):
        return changes

    def apply(self, view: SidebarModelView, changes) -> None:
        pass

    def current_for(self, view: SidebarModelView) -> SidebarModelState:
        return self

    def present(self, view: SidebarModelView) -> None:
        view.app.coordination_access.show_sidebar(view, False)


class Detached(SidebarModelState):
    """No opened service or model belongs to this view."""

    def shows_child(self, view: SidebarModelView, child: Widget) -> bool:
        return False


@dataclass(frozen=True)
class FailedSidebarState(SidebarModelState):
    observed: FailedObservation

    def shows_child(self, view: SidebarModelView, child: Widget) -> bool:
        return child is view.unavailable

    def present(self, view: SidebarModelView) -> None:
        view.unavailable.update(f"Comms unavailable\n{self.observed.error}")
        view.app.coordination_access.show_sidebar(view, view.accepts_observation())


@dataclass(frozen=True)
class BoundSidebar(SidebarModelState):
    observed: Observing

    def shows_child(self, view: SidebarModelView, child: Widget) -> bool:
        return (child is view.unavailable) == self.observed.sidebar.observation.shows_status()

    def root(self):
        return self.observed.root

    def serves(self, path) -> bool:
        return self.observed.root == path

    def observes(self, observed: Observing) -> bool:
        return self.observed is observed

    def unsubscribe(self, view: SidebarModelView) -> None:
        self.observed.sidebar.channels.unsubscribe(view.channels_changed)
        self.observed.sidebar.threads.unsubscribe(view.threads_changed)

    def current_for(self, view: SidebarModelView) -> SidebarModelState:
        if not view.accepts_observation():
            return Behind(self.observed)
        return self.present_current()

    def present(self, view: SidebarModelView) -> None:
        view.unavailable.update(self.observed.sidebar.observation.status_text())
        view.app.coordination_access.show_sidebar(view, view.accepts_observation())

    def present_current(self):
        return self


class Current(BoundSidebar):
    def shows_model(self) -> bool:
        return True

    def apply(self, view: SidebarModelView, changes) -> None:
        if changes:
            view.sync(**changes)

    @property
    def shown(self) -> SidebarModel:
        return self.observed.sidebar


class Behind(BoundSidebar):
    def present_current(self):
        return Current(self.observed)

    def changes(self, changes):
        return dict(change=AllSidebarRows(), reorder=True)


class SidebarModelView(CoreEventReceiver, ToadNode, SidebarSubscriber[Observing, FailedObservation], Widget):
    """A widget showing the observed service's sidebar model.

    Core's model is observed only while a view shows it. Changes that arrive
    while this one is hidden are applied in one pass when it shows again.
    """

    def __init__(self, *args: Widget, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.unavailable = Static("", markup=False)

    @on(events.Mount)
    async def on_mount(self) -> None:
        await self.mount(self.unavailable)
        self.watch_model_state(self.model_state)
        self.observe_core(self.app.events)
        self.observe_core(self.app.coordination_access.events)
        observed = await self.app.preparation.run_thread(
            self.app.coordination_access.observation.observed
        )
        observed.show_sidebar(self)

    @on(events.Unmount)
    def on_unmount(self) -> None:
        self.stop_showing()

    @on(events.Show)
    def on_show(self) -> None:
        self.present()

    def sidebar_visibility_changed(self) -> None:
        self.present()

    model_state: reactive[SidebarModelState] = reactive(Detached, repaint=False, always_update=True)

    def watch_model_state(self, state: SidebarModelState) -> None:
        for child in self.children:
            child.display = state.shows_child(self, child)

    @property
    def navigation_root(self):
        return self.model_state.root()

    @property
    def references(self) -> ReferenceContext:
        return self.model_state.shown.observation.require_snapshot().references

    @abstractmethod
    def accepts_observation(self) -> bool:
        """Whether this view shows the model now."""

    def model_replaced(self) -> None:
        """Retire what showed the previous service's rows."""

    @abstractmethod
    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        """Apply the model's declared row change."""

    def unsubscribe(self) -> None:
        previous = self.model_state
        self.model_state = Detached()
        previous.unsubscribe(self)

    def stop_showing(self) -> None:
        self.app.coordination_access.show_sidebar(self, False)
        self.unsubscribe()

    def bind_failed_observation(self, observed: FailedObservation) -> None:
        self.unsubscribe()
        self.model_state = FailedSidebarState(observed)
        self.model_replaced()
        self.display = True
        self.present()

    def bind_observation(self, observed: Observing) -> None:
        if self.model_state.observes(observed):
            return
        self.unsubscribe()
        self.model_state = Behind(observed)
        observed.sidebar.channels.subscribe(self.channels_changed)
        observed.sidebar.threads.subscribe(self.threads_changed)
        self.model_replaced()
        self.present()

    def channels_changed(self, changes: Changes[str]) -> None:
        self.present(
            change=ChangedChannels(frozenset((*changes.added, *changes.changed))),
            reorder=bool(changes.added or changes.removed or changes.order is not None),
        )

    def threads_changed(self, changes: Changes[str]) -> None:
        self.present(
            change=ChangedThreads(
                frozenset((*changes.added, *changes.removed, *changes.changed))
            )
        )

    def present(self, **changes) -> None:
        """Publish the next state before it applies pending model changes."""
        previous = self.model_state
        self.model_state = previous.current_for(self)
        self.model_state.present(self)
        self.model_state.apply(self, previous.changes(changes))

    @handles(CoordinationObserved)
    async def coordination_observed(self, event: CoordinationObserved) -> None:
        self.app.coordination_access.observation.observed().show_sidebar(self)

    @handles(ThreadRowStateChanged)
    async def thread_row_state_changed(self, event: ThreadRowStateChanged) -> None:
        """Repaint only the thread rows named by the app event."""
        self.present(change=ChangedThreads(event.names))
