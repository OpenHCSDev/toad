"""An open thread's status line, observed locally or marked on another route.

The toolkit-neutral `ThreadStatusOwner` lives in `toad.status_thread`; this module
keeps only the Textual `Widget` adapter.
"""

from __future__ import annotations

from agent_comms.ui_model.status import ThreadStatusModel
from textual.message import Message
from textual.reactive import var
from textual.widget import Widget

from toad.app_node import ToadNode
from toad.core_event_carrier import CoreEventReceiver
from toad.status_thread import ObservedActivity, ThreadStatusOwner  # noqa: F401 — re-export
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
