"""Who is here, drawn under the composer as the conversation kind chooses
(ConversationKind.compose_activity): a channel's active members, or a direct message's
peer with its status and Toad's activity sweep while the peer works."""

from __future__ import annotations

from array import array
from bisect import bisect_left
from collections.abc import Callable
from time import monotonic

from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.sidebar import SidebarModel
from agent_comms.ui_model.status import ThreadStatusModel
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
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
        # The ribbon is sampled once per logical pixel and Qt scales the image onto the
        # whole strip. The image used to be tagged with the device pixel ratio, which drew
        # it at 1/ratio of the strip: on a Pixel 8a (2.625) the sweep ran across the first
        # 38% of the row and its band never passed it.
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0:
            return
        # The ribbon inks one run of columns (`Ribbon.sample` is zero outside its ends), so
        # only that run is sampled: the inked columns are contiguous.
        first = max(0, int(frame.start * width))
        last = min(width, int(frame.end * width) + 1)
        x0, pixels, bars = -1, array("I"), []
        for x in range(first, last):
            start, end, amount, thickness = frame.sample((x + 0.5) / width)
            if thickness <= 0:
                if bars:
                    break
                continue
            x0 = x if x0 < 0 else x0
            ink = start.rgb(scheme).blend(end.rgb(scheme), amount)
            pixels.append((0xFF << 24) | (ink.red << 16) | (ink.green << 8) | ink.blue)
            bars.append(max(1, round(height * thickness)))
        if not bars:
            return
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        row_stride = image.bytesPerLine() // 4
        # Flat: CPython memoryviews cannot index a multi-dimensional row (`buf[y]`).
        buf = memoryview(image.bits()).cast("I")
        # Each column's ink is centred and its height rises to the body and falls again
        # (the taper is a smoothstep), so a row's ink is one run of columns around the
        # tallest: one slice write per row, found by bisecting the rising and falling sides,
        # not one Python write per pixel.
        peak = bars.index(max(bars))
        rising, falling = bars[:peak + 1], bars[peak:]
        for y in range((height - bars[peak]) // 2, (height - bars[peak]) // 2 + bars[peak]):
            def inks(bar: int, y: int = y) -> bool:
                return (height - bar) // 2 <= y < (height - bar) // 2 + bar
            left = bisect_left(rising, True, key=inks)
            right = peak + bisect_left(falling, True, key=lambda bar: not inks(bar))
            offset = y * row_stride + x0 + left
            buf[offset:offset + right - left] = pixels[left:right]
        painter = QPainter(self)
        painter.drawImage(self.rect(), image)
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
