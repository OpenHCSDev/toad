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
    from toad.widgets.observed_thread_activity import (
        ObservedThreadActivity,
        ThreadStatusOwner,
    )


class StatusThread(ABC):
    """The status source selected by a view, independent of ACP turn permissions."""

    name: str

    @classmethod
    def for_root(cls, root: Path, name: str, access) -> StatusThread:
        if access.observation.observed().observes(root):
            return LocalStatusThread(root, name)
        return OtherRouteStatusThread(root, name)

    @abstractmethod
    def bind(self, activity: ObservedThreadActivity) -> None: ...

    def refresh(self, view: ThreadStatusOwner) -> None:
        view.thread_activity.bind(self)

    def observe(self, activity: ObservedThreadActivity) -> None:
        """Only a local source acquires a scoped observation subscription."""


@dataclass(frozen=True)
class NoStatusThread(StatusThread):
    name = ""

    def bind(self, activity: ObservedThreadActivity) -> None:
        activity.show(ThreadStatusModel.pending(self.name))

    def refresh(self, view: ThreadStatusOwner) -> None:
        """A conversation without a status source has no row to refresh."""


@dataclass(frozen=True)
class LocalStatusThread(StatusThread):
    root: Path
    name: str

    def bind(self, activity: ObservedThreadActivity) -> None:
        activity.show(activity.app.coordination_access.thread_status.open(self.name))

    def observe(self, activity: ObservedThreadActivity) -> None:
        access = activity.app.coordination_access
        activity.observe_core_callback(
            access.events,
            ThreadRowsChanged,
            activity.status_changed,
            factory=partial(
                ThreadCallbackSubscription, scope=(str(self.root), self.name)
            ),
        )


@dataclass(frozen=True)
class OtherRouteStatusThread(StatusThread):
    root: Path
    name: str

    def bind(self, activity: ObservedThreadActivity) -> None:
        activity.show(ThreadStatusModel.other_route(self.name))
