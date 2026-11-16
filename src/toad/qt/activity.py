"""Who is here, drawn under the composer as the conversation kind chooses
(ConversationKind.compose_activity): a channel's active members, or a direct message's
peer with its status and Toad's activity sweep while the peer works."""

from __future__ import annotations

from time import monotonic

from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.sidebar import SidebarModel
from agent_comms.ui_model.status import ThreadStatusModel
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from ui_theme.effects import ACTIVITY_SWEEP

from toad.client.application import ClientApplication
from toad.client.connection import CoordinationAccess
from toad.client.conversation import ConversationKind
from toad.client.line_blocks import MutedRole
from toad.qt.core_events import QtCoreObserver
from toad.qt.lines import QtLineRenderer
from toad.status_thread import ObservedActivity


class ActivityLine(QLabel):
    """One muted line of reference under the composer."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.setStyleSheet(f"color: {renderer.colour(MutedRole)}; padding: 0 6px")
        self.setWordWrap(False)

    def close_activity(self) -> None:
        """Nothing observed; nothing to stop."""


class ChannelActivity(ActivityLine):
    """The channel's active members from the sidebar's rows, as Textual's collapsed
    ChannelActivity titles them; it follows every change to those rows."""

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer, conversation: ConversationKind) -> None:
        super().__init__(renderer)
        self.conversation = conversation
        self.model: SidebarModel = app.coordination_access.observation.observed().sidebar
        self.model.channels.subscribe(self.rows_changed)
        self.model.threads.subscribe(self.rows_changed)
        self.rows_changed(())

    def rows_changed(self, changes: object) -> None:
        self.setText(self.conversation.activity_title(self.conversation.active_members(self.model)))

    def close_activity(self) -> None:
        self.model.channels.unsubscribe(self.rows_changed)
        self.model.threads.unsubscribe(self.rows_changed)


class ActivitySweep(QWidget):
    """Toad's activity sweep: the shared ACTIVITY_SWEEP ribbon sampled across the strip,
    each sample's two stops blended and drawn as tall as the ribbon is thick there."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.renderer = renderer
        self.working = False
        self.started = monotonic()
        self.setFixedHeight(6)
        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / ACTIVITY_SWEEP.frames_per_second))
        self.timer.timeout.connect(self.update)

    def sweep(self, working: bool) -> None:
        self.working = working
        if working:
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        if not self.working:
            return
        frame = ACTIVITY_SWEEP.frame(monotonic() - self.started)
        scheme = self.renderer.scheme
        width, height = self.width(), self.height()
        painter = QPainter(self)
        for x in range(width):
            start, end, amount, thickness = frame.sample((x + 0.5) / width)
            if thickness <= 0:
                continue
            ink = start.rgb(scheme).blend(end.rgb(scheme), amount)
            bar = max(1, round(height * thickness))
            painter.fillRect(x, (height - bar) // 2, 1, bar, QColor(ink.hex))
        painter.end()


class PeerActivity(ObservedActivity, QtCoreObserver, QWidget):
    """A direct message's peer as Textual's ConversationSessionDetails titles it collapsed:
    its name and status summary, over the sweep while it works. The view's status thread
    binds the peer's row into it."""

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer, peer: ThreadIncarnation) -> None:
        super().__init__()
        self.app, self.peer = app, peer
        self.row = ThreadStatusModel.pending("")
        self.is_mounted = False
        self.strip = ActivitySweep(renderer)
        self.summary = ActivityLine(renderer)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.strip)
        layout.addWidget(self.summary)

    @property
    def coordination(self) -> CoordinationAccess:
        return self.app.coordination_access

    @property
    def timer(self) -> QTimer:
        return self.strip.timer

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.is_mounted:
            self.is_mounted = True
            self.start_observing()

    def show(self, row: ThreadStatusModel) -> None:
        self.row = row
        self.strip.sweep(self.working)
        self.summary.setText(" · ".join((row.name, *row.summary)))
        self.summary.setVisible(bool(row.summary and row.summary[0]))

    def close_activity(self) -> None:
        self.close_core_events()
