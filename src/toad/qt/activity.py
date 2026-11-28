"""Who is here, drawn under the composer as the conversation kind chooses
(ConversationKind.compose_activity): a channel's active members live in
`ChannelActivitySidebar` (`toad.qt.window`), reusing the shared sidebar channel tree;
this module holds Toad's activity sweep and a direct message's peer status."""

from __future__ import annotations

from collections.abc import Callable
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.status import ThreadStatusModel
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.clock import Animation
from ui_theme.effects import ACTIVITY_SWEEP, Ribbon
from ui_theme.scheme import BackgroundColour

from toad.client.application import ClientApplication
from toad.client.line_blocks import MutedRole
from toad.client.prompt_stack import ObservedSweep, SweepEffect
from toad.qt.core_events import QtCoreObserver
from toad.qt.lines import QtLineRenderer
from toad.status_thread import ObservedActivity
from toad.qt.metrics import UiGap
from toad.qt.widget_animation import QtAnimationClock, WidgetAnimation


class ActivitySweep(SweepEffect, WidgetAnimation, QWidget):
    """The shared activity ribbon painted by Qt.

    ``ACTIVITY_SWEEP`` owns its cadence and every frame's position, width, taper and
    palette, exactly as it does for Textual's ``AboveThrobber``.  Qt contributes only
    the native paint.  An indeterminate ``QProgressBar`` used to replace that frame with
    a platform-style chunk: it both looked different and drove Android's whole Widgets
    backing store continuously.
    """

    def __init__(self, renderer: QtLineRenderer, clock: QtAnimationClock) -> None:
        super().__init__()
        self.renderer = renderer
        self.working = False
        self.animation: Animation[Ribbon] | None = None
        self.clock = clock
        self._scheme_rgb_cache: tuple[object, object, QColor, dict[type, object]] | None = None
        self.setFixedHeight(self.fontMetrics().lineSpacing())
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        WidgetAnimation.bind_widget(self, self, clock)
        renderer.themed(self, self.update)

    def _scheme_colours(self):
        scheme = self.renderer.scheme
        cached = self._scheme_rgb_cache
        if cached is not None and cached[0] is scheme:
            return cached[1], cached[2], cached[3]
        bg = BackgroundColour.rgb(scheme)
        bg_qcolor = QColor(bg.hex)
        stops_map: dict[type, object] = {}
        self._scheme_rgb_cache = (scheme, bg, bg_qcolor, stops_map)
        return bg, bg_qcolor, stops_map

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

    @property
    def animation_visible(self) -> bool:
        return super().animation_visible and not self.clock.scrolling

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        background, bg_qcolor, stops_map = self._scheme_colours()
        painter.fillRect(event.rect(), bg_qcolor)
        if self.animation is None:
            return
        frame = self.animation.frame()
        gradient = QLinearGradient(0, 0, self.width(), 0)
        # Qt interpolates linear stops natively in C++. Sampling the taper boundaries and
        # each palette stop (2*N stops instead of 8*N) preserves the exact ribbon shape
        # while cutting 120 Hz Python color blending by 4x.
        scheme = self.renderer.scheme
        steps = 2 * len(frame.stops)
        span = frame.end - frame.start
        positions = {0.0, 1.0}
        positions.update(frame.start + span * step / steps for step in range(steps + 1))
        for position in sorted(max(0.0, min(1.0, place)) for place in positions):
            start, end, amount, height = frame.sample(position)
            if height <= 0.0:
                gradient.setColorAt(position, bg_qcolor)
                continue
            start_rgb = stops_map.get(start)
            if start_rgb is None:
                start_rgb = stops_map[start] = start.rgb(scheme)
            end_rgb = stops_map.get(end)
            if end_rgb is None:
                end_rgb = stops_map[end] = end.rgb(scheme)
            ink = start_rgb.blend(end_rgb, amount)
            colour = background.blend(ink, height)
            gradient.setColorAt(position, QColor(colour.red, colour.green, colour.blue))
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
