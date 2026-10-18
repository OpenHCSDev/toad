"""An open thread's status line, observed locally or read from its foreign root."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from agent_comms.coordination_errors import CoordinationReadUnavailable
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.ui_model.changes import Changes
from agent_comms.ui_model.status import ThreadStatusModel
from agent_comms.ui_model.observation import UnreadableHistory
from textual.message import Message
from textual.reactive import var
from textual.widget import Widget
from toad.core.events import ThreadRowsChanged


class StatusThread(ABC):
    """The status source selected by a view, independent of ACP turn permissions."""

    name: str

    @classmethod
    def for_root(cls, root: Path, name: str, access) -> StatusThread:
        """Both the session binding and Comms service supply absolute wire roots."""
        observed = access.observed_service
        if observed is not None and root == observed.root:
            return LocalStatusThread(name)
        return ForeignStatusThread(root, name)

    @abstractmethod
    def bind(self, activity: ObservedThreadActivity) -> None: ...

    def refresh(self, view: ThreadStatusOwner) -> None:
        view.thread_activity.bind(self)

    def rows_changed(self, activity: ObservedThreadActivity, changes: Changes[str]) -> None:
        """Only a local source consumes the observed rows."""


@dataclass(frozen=True)
class NoStatusThread(StatusThread):
    name = ""

    def bind(self, activity: ObservedThreadActivity) -> None:
        activity.show(ThreadStatusModel.pending(self.name))

    def refresh(self, view: ThreadStatusOwner) -> None:
        """A conversation without a status source has no row to refresh."""


@dataclass(frozen=True)
class LocalStatusThread(StatusThread):
    name: str

    def bind(self, activity: ObservedThreadActivity) -> None:
        activity.show(activity.app.coordination_access.thread_status.open(self.name))

    def rows_changed(self, activity: ObservedThreadActivity, changes: Changes[str]) -> None:
        if self.name in changes.changed or self.name in changes.added or self.name in changes.removed:
            self.bind(activity)


@dataclass(frozen=True)
class ForeignStatusThread(StatusThread):
    root: Path
    name: str

    def bind(self, activity: ObservedThreadActivity) -> None:
        activity.show(ThreadStatusModel.pending(self.name))

    def refresh(self, view: ThreadStatusOwner) -> None:
        super().refresh(view)
        view.run_worker(self.read_foreign_thread(view), group="foreign-thread-status", exclusive=True)

    async def read_foreign_thread(self, view: ThreadStatusOwner) -> None:
        try:
            presentation = await view.app.coordination_access.transcripts.thread_presentation(
                str(self.root), self.name)
            row = ThreadStatusModel.known(self.name, presentation)
        except CoordinationReadUnavailable:
            return  # The next coordination change retries a busy store.
        except (OSError, ValueError, RuntimeError) as error:
            presentation = None
            row = ThreadStatusModel.unreadable(self.name, UnreadableHistory.capture(error))
        if view.status_thread() != self:
            return
        view.thread_activity.show(row)
        view.foreign_thread_read(presentation)


class ActivityView:
    """The status display a conversation kind supplies, mounted or absent."""

    def bind(self, thread: StatusThread) -> None:
        raise NotImplementedError

    def show(self, row: ThreadStatusModel) -> None:
        raise NotImplementedError

    @property
    def working(self) -> bool:
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


class ObservedThreadActivity(Widget, ActivityView):
    """The composed status row; observation never starts or settles an ACP turn."""

    row: var[ThreadStatusModel] = var(lambda: ThreadStatusModel.pending(""), init=False)

    class Changed(Message):
        """The observed row changed; the view repaints what derives from it."""

    def __init__(self, *args, **kwargs) -> None:
        self.thread: StatusThread = NoStatusThread()
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        self.app.coordination_access.thread_status.rows.subscribe(self.rows_changed)

    def on_unmount(self) -> None:
        self.app.coordination_access.thread_status.rows.unsubscribe(self.rows_changed)

    def bind(self, thread: StatusThread) -> None:
        if thread != self.thread:
            self.thread = thread
            thread.bind(self)

    def rows_changed(self, changes: Changes[str]) -> None:
        self.thread.rows_changed(self, changes)

    def show(self, row: ThreadStatusModel) -> None:
        self.row = row

    def watch_row(self, row: ThreadStatusModel) -> None:
        self.activity_changed()

    def activity_changed(self) -> None:
        self.post_message(self.Changed())

    @property
    def working(self) -> bool:
        return self.row.status.working


class ThreadStatusOwner:
    """A view with a composed row and a declared status source."""

    # Before compose there is no status view yet; the kind supplies its view.
    thread_activity: ActivityView = NoActivityView()

    @property
    def _observed_working(self) -> bool:
        """Observed work cannot settle an independently owned ACP request."""
        return self.thread_activity.working

    def status_thread(self) -> StatusThread:
        raise NotImplementedError

    def thread_observed(self, event: ThreadRowsChanged) -> None:
        """Consume the observed thread's presentation once per store change."""

    def foreign_thread_read(self, presentation: ThreadPresentation | None) -> None:
        """Consume a foreign thread's presentation after its own read."""

    def refresh_thread_status(self) -> None:
        self.status_thread().refresh(self)
