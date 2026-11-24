"""Who is here, drawn under the composer as the conversation kind chooses
(ConversationKind.compose_activity): a channel's active members, or a direct message's
peer with its status and Toad's activity sweep while the peer works."""

from __future__ import annotations

from collections.abc import Callable
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.sidebar import SidebarModel
from agent_comms.ui_model.status import ThreadStatusModel
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.clock import Animation, AnimationClock
from ui_theme.effects import ACTIVITY_SWEEP, Ribbon
from ui_theme.scheme import BackgroundColour

from toad.client.application import ClientApplication
from toad.client.connection import CoordinationAccess
from toad.channel_activity_dispatch import ChannelActivityTitle
from toad.client.conversation import ConversationKind
from toad.client.fragments import Shown
from toad.client.line_blocks import NO_LINK, MutedRole
from toad.client.prompt_stack import ObservedSweep, SweepEffect
from toad.qt.core_events import QtCoreObserver
from toad.qt.lines import QtLineRenderer
from toad.status_thread import ObservedActivity
from toad.qt.metrics import UiGap
from toad.qt.widget_animation import WidgetAnimation


class ChannelActivity(ChannelActivityTitle, QLabel):
    """The shared channel activity title as a disclosure, as Textual's collapsed
    ChannelActivity draws it: `▶ N active · names`; a tap opens one `▶ name` row per active
    member. Both rows are the shared `Shown.summary` blocks the transcript's ▶ rows use."""

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer, conversation: ConversationKind) -> None:
        super().__init__()
        self.renderer = renderer
        self.shown = Shown()
        self.drawn: tuple = ()
        """The blocks the label shows."""
        self.setContentsMargins(UiGap.loose, 0, UiGap.loose, 0)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.activity_conversation = conversation
        self.activity_model: SidebarModel = app.coordination_access.observation.observed().sidebar
        self.activity_model.channels.subscribe(self.rows_changed)
        self.activity_model.threads.subscribe(self.rows_changed)
        renderer.themed(self, self.draw_again)

    def draw_again(self) -> None:
        """The scheme's colours are in the label's rich text: a scheme draws the blocks again."""
        self.drawn = ()
        self.rows_changed(())

    def rows_changed(self, changes: object) -> None:
        """Draw the title's blocks when they are other blocks than the label shows: the
        sidebar's rows change many times a minute with the same members active, and each
        change rendered the same line again and laid the label out again."""
        heading = self.shown.summary(self.activity_title, MutedRole, NO_LINK)
        members = (Shown().summary(member.name, MutedRole, NO_LINK) for member in self.members)
        blocks = (heading, *(members if self.shown.details_open else ()))
        if blocks != self.drawn:
            self.drawn = blocks
            self.setText(self.renderer.html(blocks))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.shown = self.shown.toggled()
        self.rows_changed(())

    def close_activity(self) -> None:
        self.activity_model.channels.unsubscribe(self.rows_changed)
        self.activity_model.threads.unsubscribe(self.rows_changed)


class ActivitySweep(SweepEffect, WidgetAnimation, QWidget):
    """The shared activity ribbon painted by Qt.

    ``ACTIVITY_SWEEP`` owns its cadence and every frame's position, width, taper and
    palette, exactly as it does for Textual's ``AboveThrobber``.  Qt contributes only
    the native paint.  An indeterminate ``QProgressBar`` used to replace that frame with
    a platform-style chunk: it both looked different and drove Android's whole Widgets
    backing store continuously.
    """

    def __init__(self, renderer: QtLineRenderer, clock: AnimationClock) -> None:
        super().__init__()
        self.renderer = renderer
        self.working = False
        self.animation: Animation[Ribbon] | None = None
        self.clock = clock
        self.setFixedHeight(self.fontMetrics().lineSpacing())
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        WidgetAnimation.bind_widget(self, self, clock)
        renderer.themed(self, self.update)

    def sweep(self, working: bool) -> None:
        if working == self.working:
            return
        self.working = working
        if working:
            self.animation = self.animation or self.clock.start(self.effect, self)
        elif self.animation is not None:
            self.animation.stop()
            self.animation = None
        self.update()

    def repaint(self) -> None:
        """A shared clock tick invalidates this strip; Qt schedules its native paint."""
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        background = BackgroundColour.rgb(self.renderer.scheme)
        painter.fillRect(event.rect(), QColor(background.hex))
        if self.animation is None:
            return
        frame = self.animation.frame()
        gradient = QLinearGradient(0, 0, self.width(), 0)
        # Qt interpolates these samples on the GPU/native paint path.  The samples come
        # from Ribbon.sample itself, so Qt owns no second taper, palette order or phase.
        steps = 8 * len(frame.stops)
        span = frame.end - frame.start
        positions = {0.0, 1.0}
        positions.update(frame.start + span * step / steps for step in range(steps + 1))
        for position in sorted(max(0.0, min(1.0, place)) for place in positions):
            start, end, amount, height = frame.sample(position)
            ink = start.rgb(self.renderer.scheme).blend(end.rgb(self.renderer.scheme), amount)
            colour = background.blend(ink, height)
            gradient.setColorAt(position, QColor(colour.hex))
        painter.fillRect(self.rect(), gradient)


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
        self.summary = ElidedLine()
        renderer.themed(self.summary, lambda: self.summary.setStyleSheet(renderer.color_style(MutedRole)))
        self.summary.setContentsMargins(UiGap.loose, 0, UiGap.loose, 0)
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
