"""Who is here, drawn under the composer as the conversation kind chooses
(ConversationKind.compose_activity): a channel's active members, or a direct message's
peer with its status and Toad's activity sweep while the peer works."""

from __future__ import annotations

from collections.abc import Callable
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.sidebar import SidebarModel
from agent_comms.ui_model.status import ThreadStatusModel
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget
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


class ActivitySweep(QProgressBar):
    """Toad's activity sweep: the shared ACTIVITY_SWEEP ribbon drawn across the strip as one
    native Qt style animation. Python publishes only the working transition; Qt's C++ style
    owns every frame after that. Android cannot embed a Quick scene in its Widgets surface:
    its Quick child becomes a second full-screen surface and covers the application black."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.renderer = renderer
        self.working = False
        self.setTextVisible(False)
        self.setRange(0, 1)
        self.setValue(0)
        self.setFixedHeight(self.fontMetrics().lineSpacing())
        renderer.themed(self, self.follow_theme)

    def follow_theme(self) -> None:
        colours = []
        for tone in ACTIVITY_SWEEP.stops:
            ink = tone.rgb(self.renderer.scheme)
            colours.append(QColor(ink.red, ink.green, ink.blue).name())
        self.setStyleSheet(
            "QProgressBar { border: 0; background: transparent; }"
            "QProgressBar::chunk { border: 0; "
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {colours[0]},"
            f"stop:0.5 {colours[1]},stop:1 {colours[2]}); }}"
        )

    def sweep(self, working: bool) -> None:
        if working == self.working:
            return
        self.working = working
        self.setRange(0, 0) if working else self.setRange(0, 1)


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
