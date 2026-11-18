"""Who is here, drawn under the composer as the conversation kind chooses
(ConversationKind.compose_activity): a channel's active members, or a direct message's
peer with its status and Toad's activity sweep while the peer works."""

from __future__ import annotations

from time import monotonic

from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.sidebar import SidebarModel
from agent_comms.ui_model.status import ThreadStatusModel
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.effects import ACTIVITY_SWEEP

from toad.client.application import ClientApplication
from toad.client.connection import CoordinationAccess
from toad.channel_activity_dispatch import ChannelActivityTitle
from toad.client.conversation import ConversationKind
from toad.client.line_blocks import MutedRole
from toad.client.prompt_stack import ObservedSweep
from toad.qt.core_events import QtCoreObserver
from toad.qt.lines import QtLineRenderer
from toad.status_thread import ObservedActivity
from toad.qt.metrics import UiGap


class ActivityLine(ElidedLine):
    """One muted line of reference under the composer, cut to the width the page has."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.setStyleSheet(renderer.color_style(MutedRole))
        self.setContentsMargins(UiGap.loose, 0, UiGap.loose, 0)

    def close_activity(self) -> None:
        """Nothing observed; nothing to stop."""


class ChannelActivity(ChannelActivityTitle, ActivityLine):
    """The shared channel activity title as one line; it follows every change to the rows."""

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer, conversation: ConversationKind) -> None:
        super().__init__(renderer)
        self.activity_conversation = conversation
        self.activity_model: SidebarModel = app.coordination_access.observation.observed().sidebar
        self.activity_model.channels.subscribe(self.rows_changed)
        self.activity_model.threads.subscribe(self.rows_changed)
        self.rows_changed(())

    def rows_changed(self, changes: object) -> None:
        self.setText(self.activity_title)

    def close_activity(self) -> None:
        self.activity_model.channels.unsubscribe(self.rows_changed)
        self.activity_model.threads.unsubscribe(self.rows_changed)


class ActivitySweep(QWidget):
    """Toad's activity sweep: the shared ACTIVITY_SWEEP ribbon sampled across the strip,
    each sample's two stops blended and drawn as tall as the ribbon is thick there."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.renderer = renderer
        self.working = False
        self.started = monotonic()
        # One text row, always reserved, as Textual's throbber row: only its paint changes.
        self.setFixedHeight(self.fontMetrics().lineSpacing())
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
        if width <= 0 or height <= 0:
            return
        # One Python-sampled image → one C++ blit. The 20-fps `paintEvent` used to issue
        # one Python→Qt fillRect per pixel-column (~1000 crossings per paint on a Pixel
        # 8a). Now one QImage is filled in Python via a uint32 memoryview — pure CPython
        # integer writes, no Qt round-trips — and painted with a single drawImage. Each
        # column still gets its sampled colour and its thickness-centred band.
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setDevicePixelRatio(self.devicePixelRatioF() or 1.0)
        row_stride = image.bytesPerLine() // 4
        buf = memoryview(image.bits()).cast("I", shape=[height, row_stride])
        for x in range(width):
            start, end, amount, thickness = frame.sample((x + 0.5) / width)
            if thickness <= 0:
                continue
            ink = start.rgb(scheme).blend(end.rgb(scheme), amount)
            pixel = (0xFF << 24) | (ink.red << 16) | (ink.green << 8) | ink.blue
            bar = max(1, round(height * thickness))
            top = (height - bar) // 2
            for y in range(top, top + bar):
                buf[y][x] = pixel
        painter = QPainter(self)
        painter.drawImage(0, 0, image)
        painter.end()


class QtObservedSweep(ObservedSweep, ActivitySweep):
    """The sweep under a thread view's transcript, Textual's `AboveThrobber`: it paints the
    view's `working()` answer through the shared `ObservedSweep`, never a busy copy."""

    def sync(self) -> None:
        self.sweep(self.read_busy())


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
