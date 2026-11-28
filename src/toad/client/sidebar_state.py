"""Toolkit-neutral sidebar observation states and state machine shared by Textual and Qt.

`SidebarModelState` (and its members `Detached`, `FailedSidebarState`, `BoundSidebar`,
`Current`, `Behind`) and `SidebarStateMachine` drive observation binding, change dispatch,
and status presentation through abstract toolkit hooks, with zero UI imports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent_comms.messaging.display_references import ReferenceContext
from agent_comms.ui_model.changes import Changes
from agent_comms.ui_model.sidebar import SidebarModel

from toad.client.connection import FailedObservation, Observing
from toad.client.sidebar_lines import SidebarStatusLine
from toad.client.subscribers import SidebarSubscriber
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

    def retained_root(self):
        """Last observed bus root kept across a transient outage, or None."""
        return None

    def retained_model(self) -> SidebarModel | None:
        """Last shown SidebarModel kept across a transient outage, or None."""
        return None

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
    retained_root_path: object = None
    retained_sidebar: SidebarModel | None = None

    def serves(self, path) -> bool:
        return self.retained_root_path is not None and self.retained_root_path == path

    def retained_root(self):
        return self.retained_root_path

    def retained_model(self) -> SidebarModel | None:
        return self.retained_sidebar

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

    def retained_root(self):
        return self.observed.root

    def retained_model(self) -> SidebarModel | None:
        return self.observed.sidebar

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
        previous = self.model_state
        retained_root = previous.retained_root()
        retained_model = previous.retained_model()
        self.unsubscribe()
        self.model_state = FailedSidebarState(
            observed,
            retained_root_path=retained_root,
            retained_sidebar=retained_model,
        )
        if retained_model is None:
            self.model_replaced()
        self.present()

    def bind_observation(self, observed: Observing) -> None:
        if self.model_state.observes(observed):
            return
        same_root = self.model_state.serves(observed.root)
        self.unsubscribe()
        self.model_state = Behind(observed)
        observed.sidebar.channels.subscribe(self.channels_changed)
        observed.sidebar.threads.subscribe(self.threads_changed)
        if not same_root:
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
