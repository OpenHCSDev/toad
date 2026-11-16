"""An open thread's status line, observed locally or marked on another route."""

from __future__ import annotations
from abc import abstractmethod



from agent_comms.ui_model.status import ThreadStatusModel
from textual.message import Message
from textual.reactive import var
from textual.widget import Widget

from toad.app_node import ToadNode
from toad.core.events import ThreadRowsChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.status_thread import ObservedActivity, StatusOwner, StatusThread
from textual.events import Mount
from textual import on


class ObservedThreadActivity(ObservedActivity, CoreEventReceiver, ToadNode, Widget):
    """The composed status row; observation never starts or settles an ACP turn."""

    row: var[ThreadStatusModel] = var(lambda: ThreadStatusModel.pending(""), init=False)

    class Changed(Message):
        """The observed row changed; the view repaints what derives from it."""

    @property
    def coordination(self):
        return self.app.coordination_access

    @on(Mount)
    def on_mount(self) -> None:
        self.start_observing()

    def show(self, row: ThreadStatusModel) -> None:
        self.row = row

    def watch_row(self, row: ThreadStatusModel) -> None:
        self.activity_changed()

    def activity_changed(self) -> None:
        self.post_message(self.Changed())

class ThreadStatusOwner(StatusOwner, ToadNode):
    """A view with a composed row and a declared status source."""

    @property
    def _observed_working(self) -> bool:
        """Observed work cannot settle an independently owned ACP request."""
        return self.thread_activity.working

    @abstractmethod
    def status_thread(self) -> StatusThread:
        ...

    def thread_observed(self, event: ThreadRowsChanged) -> None:
        """Consume the observed thread's presentation once per store change."""

    def refresh_thread_status(self) -> None:
        self.status_thread().refresh(self)
