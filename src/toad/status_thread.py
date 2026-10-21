"""Thread status sources, independent of their mounted activity view."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.ui_model.status import ThreadStatusModel

from toad.core.events import ThreadRowsChanged
from toad.core_event_carrier import ThreadCallbackSubscription

if TYPE_CHECKING:
    from toad.widgets.observed_thread_activity import ObservedThreadActivity, ThreadStatusOwner


class StatusThread(ABC):
    name: str

    @staticmethod
    def route(root: Path, access) -> type[RoutedStatusThread]:
        return LocalStatusThread if access.observation.observed().observes(root) else OtherRouteStatusThread

    @classmethod
    def for_root(cls, root: Path, name: str, access) -> StatusThread:
        return cls.route(root, access)(root, name)

    @classmethod
    def for_conversation(cls, root: Path, conversation, access) -> StatusThread:
        return cls.route(root, access).conversation(root, conversation, access)

    @abstractmethod
    def bind(self, activity: ObservedThreadActivity) -> None: ...

    def refresh(self, view: ThreadStatusOwner) -> None:
        view.thread_activity.bind(self)

    def observe(self, activity: ObservedThreadActivity) -> None:
        """Only a local source acquires an observation subscription."""


@dataclass(frozen=True)
class NoStatusThread(StatusThread):
    name = ""

    def bind(self, activity: ObservedThreadActivity) -> None:
        activity.show(ThreadStatusModel.pending(self.name))

    def refresh(self, view: ThreadStatusOwner) -> None:
        """A conversation without a status source has no row to refresh."""


@dataclass(frozen=True)
class RoutedStatusThread(StatusThread):
    root: Path
    name: str

    @classmethod
    @abstractmethod
    def conversation(cls, root: Path, conversation, access) -> RoutedStatusThread: ...


class LocalStatusThread(RoutedStatusThread):
    @classmethod
    def conversation(cls, root: Path, conversation, access) -> LocalStatusThread:
        references = access.observation.observed().sidebar.observation.require_snapshot().references
        return cls(root, conversation.destination(references).name)

    def bind(self, activity: ObservedThreadActivity) -> None:
        activity.show(activity.app.coordination_access.thread_status.open(self.name))

    def observe(self, activity: ObservedThreadActivity) -> None:
        access = activity.app.coordination_access
        activity.observe_core_callback(
            access.events,
            ThreadRowsChanged,
            activity.status_changed,
            factory=partial(ThreadCallbackSubscription, scope=(str(self.root), self.name)),
        )


class OtherRouteStatusThread(RoutedStatusThread):
    @classmethod
    def conversation(cls, root: Path, conversation, access) -> OtherRouteStatusThread:
        return cls(root, conversation.initial_label)

    def bind(self, activity: ObservedThreadActivity) -> None:
        activity.show(ThreadStatusModel.other_route(self.name))
