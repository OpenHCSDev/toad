"""Thread status sources, independent of their mounted activity view."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from agent_comms.ui_model.status import ThreadStatusModel
from textual.abstract_hooks import AbstractHooksMeta


class ActivityView(metaclass=AbstractHooksMeta):
    """The status display a conversation kind supplies, mounted or absent."""

    @abstractmethod
    def bind(self, thread: StatusThread) -> None:
        ...

    @abstractmethod
    def show(self, row: ThreadStatusModel) -> None:
        ...

    @property
    @abstractmethod
    def working(self) -> bool:
        ...

    def show_open_thread(self, name: str) -> None:
        """Show the row this process's own observation keeps for an open thread."""
        raise NotImplementedError

    def observe_thread_rows(self, root: Path, name: str) -> None:
        """Repaint whenever this root's row for the thread changes."""
        raise NotImplementedError


@dataclass(frozen=True)
class NoActivityView(ActivityView):
    """No status row, widget lifetime, subscription or paint work."""

    def bind(self, thread: StatusThread) -> None:
        pass

    def show(self, row: ThreadStatusModel) -> None:
        pass

    @property
    def working(self) -> bool:
        return False


class StatusOwner:
    """A view with a status row: the activity a status thread binds into."""

    thread_activity: ActivityView = NoActivityView()


class StatusThread(ABC):
    name: str

    @staticmethod
    def route(root: Path, access) -> type[RoutedStatusThread]:
        return (
            LocalStatusThread
            if access.observation.observed().observes(root)
            else OtherRouteStatusThread
        )

    @classmethod
    def for_root(cls, root: Path, name: str, access) -> StatusThread:
        return cls.route(root, access)(root, name)

    @classmethod
    def for_conversation(cls, root: Path, conversation, access) -> StatusThread:
        return cls.route(root, access).conversation(root, conversation, access)

    @abstractmethod
    def bind(self, activity: ActivityView) -> None: ...

    def refresh(self, view: StatusOwner) -> None:
        view.thread_activity.bind(self)

    def observe(self, activity: ActivityView) -> None:
        """Only a local source acquires an observation subscription."""


@dataclass(frozen=True)
class NoStatusThread(StatusThread):
    name = ""

    def bind(self, activity: ActivityView) -> None:
        activity.show(ThreadStatusModel.pending(self.name))

    def refresh(self, view: StatusOwner) -> None:
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
        references = (
            access.observation.observed()
            .sidebar.observation.thread_names()
        )
        return cls(root, conversation.destination(references).name)

    def bind(self, activity: ActivityView) -> None:
        activity.show_open_thread(self.name)

    def observe(self, activity: ActivityView) -> None:
        activity.observe_thread_rows(self.root, self.name)


class OtherRouteStatusThread(RoutedStatusThread):
    @classmethod
    def conversation(cls, root: Path, conversation, access) -> OtherRouteStatusThread:
        return cls(root, conversation.initial_label)

    def bind(self, activity: ActivityView) -> None:
        activity.show(ThreadStatusModel.other_route(self.name))
