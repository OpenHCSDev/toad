"""Who is here, drawn under the composer as the conversation kind chooses
(ConversationKind.compose_activity): a channel's active members, or a direct message's
peer with its status and Toad's activity sweep while the peer works."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.sidebar import SidebarModel
from agent_comms.ui_model.status import ThreadStatusModel
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPolygonF
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.effects import ACTIVITY_SWEEP

from toad.client.application import ClientApplication
from toad.client.connection import CoordinationAccess
from toad.channel_activity_dispatch import ChannelActivityTitle
from toad.client.conversation import ConversationKind
from toad.client.fragments import Shown
from toad.client.line_blocks import NO_LINK, MutedRole
from toad.client.prompt_stack import ObservedSweep
from toad.qt.core_events import QtCoreObserver
from toad.qt.lines import QtLineRenderer
from toad.status_thread import ObservedActivity
from toad.qt.metrics import UiGap


class ActivityLine(ElidedLine):
    """One muted line of reference under the composer, cut to the width the page has."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        renderer.themed(self, lambda: self.setStyleSheet(renderer.color_style(MutedRole)))
        self.setContentsMargins(UiGap.loose, 0, UiGap.loose, 0)

    def close_activity(self) -> None:
        """Nothing observed; nothing to stop."""


class ChannelActivity(ChannelActivityTitle, QLabel):
    """The shared channel activity title as a disclosure, as Textual's collapsed
    ChannelActivity draws it: `▶ N active · names`; a tap opens one `▶ name` row per active
    member. Both rows are the shared `Shown.summary` blocks the transcript's ▶ rows use."""

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer, conversation: ConversationKind) -> None:
        super().__init__()
        self.renderer = renderer
        self.shown = Shown()
        self.setContentsMargins(UiGap.loose, 0, UiGap.loose, 0)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.activity_conversation = conversation
        self.activity_model: SidebarModel = app.coordination_access.observation.observed().sidebar
        self.activity_model.channels.subscribe(self.rows_changed)
        self.activity_model.threads.subscribe(self.rows_changed)
        self.rows_changed(())

    def rows_changed(self, changes: object) -> None:
        heading = self.shown.summary(self.activity_title, MutedRole, NO_LINK)
        members = (Shown().summary(member.name, MutedRole, NO_LINK) for member in self.members)
        self.setText(self.renderer.html((heading, *(members if self.shown.details_open else ()))))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.shown = self.shown.toggled()
        self.rows_changed(())

    def close_activity(self) -> None:
        self.activity_model.channels.unsubscribe(self.rows_changed)
        self.activity_model.threads.unsubscribe(self.rows_changed)


class ActivitySweep(QWidget):
    """Toad's activity sweep: the shared ACTIVITY_SWEEP ribbon drawn across the strip as one
    filled outline, its colours a gradient sampled from the ribbon and its height the
    ribbon's thickness, tapered at both tails as `Ribbon.sample` says.

    The effect's shape, colours and timing are shared with Textual; how often it is drawn is
    each toolkit's own. A terminal draws whole cells, so the effect's 20 frames a second already
    move the band a cell at a time; Qt draws pixels, and at 20 a second the band jumped about
    6 px a frame on the phone and looked laggy (Tristan, 2026-11-18). Qt draws at the screen's
    refresh rate, and each frame is 33 ribbon samples and one antialiased fill in Qt, where it
    was a Python sample and a pixel write per column."""

    samples = 32
    """Points along the ribbon: each gives a gradient stop and the outline's half-height."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.renderer = renderer
        self.working = False
        self.started = monotonic()
        # One text row, always reserved, as Textual's throbber row: only its paint changes.
        self.setFixedHeight(self.fontMetrics().lineSpacing())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)

    def sweep(self, working: bool) -> None:
        self.working = working
        if working:
            screen = self.screen()
            rate = screen.refreshRate() if screen is not None else 0.0
            self.timer.start(max(8, round(1000 / (rate if rate >= 20 else 60))))
        else:
            self.timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        if not self.working:
            return
        frame = ACTIVITY_SWEEP.frame(monotonic() - self.started)
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0 or frame.end <= frame.start:
            return
        scheme = self.renderer.scheme
        left, right = frame.start * width, frame.end * width
        gradient = QLinearGradient(left, 0.0, right, 0.0)
        upper, lower = [], []
        for step in range(self.samples + 1):
            place = step / self.samples
            x = left + (right - left) * place
            # The ribbon's ends sample as no ink; their colour is the one just inside.
            inside = frame.start + (frame.end - frame.start) * min(max(place, 1e-6), 1 - 1e-6)
            start, end, amount, _ = frame.sample(inside)
            ink = start.rgb(scheme).blend(end.rgb(scheme), amount)
            gradient.setColorAt(place, QColor(ink.red, ink.green, ink.blue))
            half = height * frame.sample(x / width)[3] / 2
            upper.append(QPointF(x, height / 2 - half))
            lower.append(QPointF(x, height / 2 + half))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawPolygon(QPolygonF(upper + lower[::-1]))
        painter.end()


class QtObservedSweep(ObservedSweep, ActivitySweep):
    """The sweep under a thread view's transcript, Textual's `AboveThrobber`: it paints the
    view's `working()` answer through the shared `ObservedSweep`, never a busy copy."""

    def sync(self) -> None:
        self.sweep(self.read_busy())


class PeerActivity(ObservedActivity, QtCoreObserver, QWidget):
    """A direct message's peer as Textual's ConversationSessionDetails titles it collapsed:
    its name and status summary. The view's status thread binds the peer's row into it;
    each row asks the view to sync its working answer, which the view's one sweep paints."""

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer, peer: ThreadIncarnation,
                 changed: Callable[[], None]) -> None:
        super().__init__()
        self.app, self.peer, self.changed = app, peer, changed
        self.row = ThreadStatusModel.pending("")
        self.is_mounted = False
        self.summary = ActivityLine(renderer)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.summary)

    @property
    def coordination(self) -> CoordinationAccess:
        return self.app.coordination_access

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.is_mounted:
            self.is_mounted = True
            self.start_observing()

    def show(self, row: ThreadStatusModel) -> None:
        self.row = row
        self.changed()
        self.summary.setText(" · ".join((row.name, *row.summary)))
        self.summary.setVisible(bool(row.summary and row.summary[0]))

    def close_activity(self) -> None:
        self.close_core_events()
