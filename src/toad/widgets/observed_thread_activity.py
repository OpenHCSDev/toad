"""An open thread's status line, observed locally or read from its foreign root."""

from __future__ import annotations

from dataclasses import dataclass

from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.ui_model.status import ThreadStatusModel
from textual.message import Message
from textual.reactive import var
from textual.widget import Widget

from toad.app_node import ToadNode
from toad.core.events import ThreadRowsChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.status_thread import NoStatusThread, StatusThread


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


class ObservedThreadActivity(CoreEventReceiver, ToadNode, Widget, ActivityView):
    """The composed status row; observation never starts or settles an ACP turn."""

    row: var[ThreadStatusModel] = var(lambda: ThreadStatusModel.pending(""), init=False)

    class Changed(Message):
        """The observed row changed; the view repaints what derives from it."""

    def __init__(self, *args, **kwargs) -> None:
        self.thread: StatusThread = NoStatusThread()
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        self.thread.observe(self)
        self.thread.bind(self)

    def bind(self, thread: StatusThread) -> None:
        if thread != self.thread:
            self.retire_core_observations(self.app.coordination_access.events)
            self.thread = thread
            thread.observe(self)
            thread.bind(self)

    def status_changed(self, event: ThreadRowsChanged) -> None:
        self.thread.bind(self)

    def show(self, row: ThreadStatusModel) -> None:
        self.row = row

    def watch_row(self, row: ThreadStatusModel) -> None:
        self.activity_changed()

    def activity_changed(self) -> None:
        self.post_message(self.Changed())

    @property
    def working(self) -> bool:
        return self.row.status.working


class ThreadStatusOwner(ToadNode):
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

    def foreign_thread_read(self, presentation: ThreadPresentation) -> None:
        """Consume a foreign thread's presentation after its own read."""

    def refresh_thread_status(self) -> None:
        self.status_thread().refresh(self)
