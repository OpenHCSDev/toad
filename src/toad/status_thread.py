"""Thread status sources, independent of their mounted activity view."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.ui_model.status import ThreadStatusModel

from toad.client.subscribers import CoreObserver, ThreadCallbackSubscription
from toad.conversation_turn import ConversationTurn
from toad.core.events import ThreadRowsChanged

if TYPE_CHECKING:
    from collections.abc import Callable


class ActivityView:
    """The status display a conversation kind supplies, mounted or absent.

    A plain parent: the mounted view brings its toolkit's metaclass."""

    def bind(self, thread: StatusThread) -> None:
        raise NotImplementedError

    def show(self, row: ThreadStatusModel) -> None:
        raise NotImplementedError

    @property
    def working(self) -> bool:
        raise NotImplementedError

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


class ObservedActivity(CoreObserver, ActivityView):
    """An activity view that follows its status thread's row: binding another thread
    observes it instead, every change to the row binds it again, and the thread is working
    when its row says so. The native view stores the row it is shown and repaints."""

    thread: StatusThread = NoStatusThread()
    row: ThreadStatusModel
    # Whether the native view has been shown; before that, start_observing is still to come.
    is_mounted: bool

    @property
    def coordination(self):
        """The coordination access whose events and open-thread rows this view reads."""
        return self.app.coordination_access

    def start_observing(self) -> None:
        """The view is shown: observe its thread and show its row."""
        self.thread.observe(self)
        self.thread.bind(self)

    def bind(self, thread: StatusThread) -> None:
        if thread != self.thread:
            self.thread = thread
            if self.is_mounted:
                self.retire_core_observations(self.coordination.events)
                thread.observe(self)
                thread.bind(self)

    def status_changed(self, event: ThreadRowsChanged) -> None:
        self.thread.bind(self)

    def show_open_thread(self, name: str) -> None:
        self.show(self.coordination.thread_status.open(name))

    def observe_thread_rows(self, root: Path, name: str) -> None:
        self.observe_core_callback(
            self.coordination.events,
            ThreadRowsChanged,
            self.status_changed,
            factory=partial(ThreadCallbackSubscription, scope=(str(root), name)),
        )

    @property
    def working(self) -> bool:
        return self.row.status.is_working()


class ThreadStatusOwner(StatusOwner):
    """A view with a composed row and a declared status source.

    Toolkit-neutral: both the Textual conversation widget and the Qt session view inherit
    this beside their own frontend base. The inherited `StatusOwner` is already neutral;
    the Textual-only `ToadNode` mixin stays on the widget subclass that needs DOMNode.
    """

    @property
    def _observed_working(self) -> bool:
        """Observed work cannot settle an independently owned ACP request."""
        return self.thread_activity.working

    status_thread: Callable[[], StatusThread]
    """The thread status this view reads: a transcript view's scope opens it
    (`TranscriptView.status_thread`), a wire view's page source."""

    def refresh_thread_status(self) -> None:
        self.status_thread().refresh(self)


class WorkingStatusOwner(ThreadStatusOwner):
    """A conversation whose activity sweep reads one answer: its own turn is busy, the
    thread it observes is working, or its saved history is still loading.

    Toolkit-neutral: Textual's `Conversation` and Qt's `QtThreadView` both inherit it, so
    neither frontend recomputes "is it thinking" from its own copy of the state."""

    turns: ConversationTurn

    def history_loading(self) -> bool:
        """Whether this view's history is reading its first page: only a wire history pages
        in under a loading row, and its view answers for it."""
        return False

    def working(self) -> bool:
        return self.turns.owner.busy or self._observed_working or self.history_loading()
