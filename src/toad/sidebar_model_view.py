"""A native view's binding to the route's observed sidebar model.

The state family (`SidebarModelState` and its members) and the state-transition
machinery (`SidebarStateMachine`) are toolkit-neutral: a view supplies the
abstract hooks each state drives, so both Textual's `SidebarModelView` and
Qt's `Sidebar` inherit the same transitions instead of restating them.
"""

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
from toad.client.connection import FailedObservation, Observing
from toad.client.sidebar_lines import SidebarStatusLine
from toad.client.subscribers import SidebarSubscriber
from toad.core.events import ThreadRowStateChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.sidebar_changes import (
    AllSidebarRows,
    ChangedChannels,
    ChangedThreads,
    SidebarChange,
)

EMPTY = SidebarModel(lambda callback: None)


class SidebarModelState(ABC):
    def shows_child(self, view: SidebarStateMachine, child) -> bool:
        """Whether this state's sidebar displays this direct child (Textual visibility hook).

        Default: hide every child. Backends with their own visibility story (Qt) ignore this.
        """
        return False

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

    def unsubscribe(self, view: SidebarStateMachine) -> None:
        pass

    def changes(self, changes):
        return changes

    def apply(self, view: SidebarStateMachine, changes) -> None:
        pass

    def current_for(self, view: SidebarStateMachine) -> SidebarModelState:
        return self

    def shows_rows(self, view: SidebarStateMachine) -> bool:
        return view.accepts_observation()

    def present(self, view: SidebarStateMachine) -> None:
        view.hide_status()
        view.coordination_access().update_sidebar_interest()


class Detached(SidebarModelState):
    """No opened service or model belongs to this view."""

    def shows_rows(self, view: SidebarStateMachine) -> bool:
        return False


@dataclass(frozen=True)
class FailedSidebarState(SidebarModelState):
    observed: FailedObservation

    def shows_child(self, view: SidebarStateMachine, child) -> bool:
        return child is view.unavailable

    def present(self, view: SidebarStateMachine) -> None:
        view.show_status(SidebarStatusLine.unavailable_text(self.observed.error))
        view.coordination_access().update_sidebar_interest()


@dataclass(frozen=True)
class BoundSidebar(SidebarModelState):
    observed: Observing

    def shows_child(self, view: SidebarStateMachine, child) -> bool:
        return (child is view.unavailable) == self.observed.sidebar.observation.shows_status()

    def root(self):
        return self.observed.root

    def serves(self, path) -> bool:
        return self.observed.root == path

    def observes(self, observed: Observing) -> bool:
        return self.observed is observed

    def unsubscribe(self, view: SidebarStateMachine) -> None:
        self.observed.sidebar.channels.unsubscribe(view.channels_changed)
        self.observed.sidebar.threads.unsubscribe(view.threads_changed)

    def current_for(self, view: SidebarStateMachine) -> SidebarModelState:
        if not view.accepts_observation():
            return Behind(self.observed)
        return self.present_current()

    def present(self, view: SidebarStateMachine) -> None:
        observation = self.observed.sidebar.observation
        if observation.shows_status():
            view.show_status(observation.status_text())
        else:
            view.hide_status()
        view.coordination_access().update_sidebar_interest()

    def present_current(self):
        return self


class Current(BoundSidebar):
    def shows_model(self) -> bool:
        return True

    def apply(self, view: SidebarStateMachine, changes) -> None:
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


class SidebarStateMachine(SidebarSubscriber[Observing, FailedObservation]):
    """The toolkit-neutral state transitions and change-dispatch of a sidebar view.

    A backend mixes this in alongside its toolkit's widget/subscription base; the state's
    `present` drives the view through `show_status`/`hide_status`/`coordination_access` so
    the transitions stay shared. Qt and Textual both inherit this instead of restating the
    bind/present/apply chain.
    """

    model_state: SidebarModelState = Detached()
    """The current observation state. Textual overrides this as a `reactive`."""

    @abstractmethod
    def accepts_observation(self) -> bool:
        """Whether this view shows the model now."""

    @abstractmethod
    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        """Apply the model's declared row change."""

    @abstractmethod
    def show_status(self, text: str) -> None:
        """Render a status/unavailable message in this view's own label widget."""

    @abstractmethod
    def hide_status(self) -> None:
        """Hide the status/unavailable label this view owns."""

    @abstractmethod
    def coordination_access(self):
        """The CoordinationAccess facade the state machine talks to."""

    def shows_sidebar(self) -> bool:
        return self.model_state.shows_rows(self)

    @property
    def navigation_root(self):
        return self.model_state.root()

    @property
    def references(self) -> ReferenceContext:
        return self.model_state.shown.observation.require_snapshot().references

    def model_replaced(self) -> None:
        """Retire what showed the previous service's rows."""

    def unsubscribe(self) -> None:
        previous = self.model_state
        self.model_state = Detached()
        previous.unsubscribe(self)

    def stop_showing(self) -> None:
        self.coordination_access().leave_sidebar(self)
        self.unsubscribe()

    def bind_failed_observation(self, observed: FailedObservation) -> None:
        self.unsubscribe()
        self.model_state = FailedSidebarState(observed)
        self.model_replaced()
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
