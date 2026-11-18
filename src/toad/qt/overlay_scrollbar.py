"""A scroll area's vertical bar drawn over its text while it moves (`Scrollbar.overlay`).

A bar beside the text takes its width for good; this one floats over the viewport's right
edge only while the area scrolls, and fades out a moment after it goes still. It mirrors the
area's own bar (hidden, still the model of the position), so dragging it scrolls the area and
any scroll of the area, by wheel, key, finger or code, shows it. Once faded it is hidden, so
it never takes a tap meant for the text under it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtWidgets import QAbstractScrollArea, QGraphicsOpacityEffect, QScrollBar
from ui_theme.clock import AnimationClock
from ui_theme.scheme import SurfaceHoverColour

from toad.motion import SCROLLBAR_FADE, TransitionTarget
from toad.qt.lines import QtLineRenderer
from toad.qt.widget_animation import WidgetAnimation


class ScrollbarFade(WidgetAnimation, TransitionTarget):
    """The overlay bar fading out on the app's clock; it is hidden where the fade lands."""

    def __init__(self, bar: OverlayScrollBar, clock: AnimationClock) -> None:
        self.bar = bar
        self.bind_widget(bar, clock)
        self.start_transition(clock, SCROLLBAR_FADE)

    def apply_amount(self, amount: float) -> None:
        self.bar.opacity.setOpacity(amount)

    def land(self) -> None:
        self.bar.fade = None
        self.bar.hide()


class OverlayScrollBar(QScrollBar):
    """The overlay for one area; `follow` attaches it, or detaches it at width 0."""

    STILL_MS = 1000
    """How long the area stays still before the bar fades."""

    def __init__(self, area: QAbstractScrollArea, clock: AnimationClock, renderer: QtLineRenderer) -> None:
        super().__init__(Qt.Orientation.Vertical, area)
        self.area, self.clock, self.renderer = area, clock, renderer
        self.source = area.verticalScrollBar()
        self.thickness = 0
        self.fade: ScrollbarFade | None = None
        self.opacity = QGraphicsOpacityEffect(self)
        self.opacity.setOpacity(1.0)
        self.setGraphicsEffect(self.opacity)
        self.still = QTimer(self)
        self.still.setSingleShot(True)
        self.still.setInterval(self.STILL_MS)
        self.still.timeout.connect(self.fade_out)
        self.source.rangeChanged.connect(self.setRange)
        self.source.valueChanged.connect(self.moved)
        self.valueChanged.connect(self.source.setValue)
        self.geometry_watch = _ViewportGeometry(self)
        area.viewport().installEventFilter(self.geometry_watch)
        renderer.themed(self, self.paint_colours)
        self.hide()

    def paint_colours(self) -> None:
        """Only the handle shows, a raised tier over whatever text it floats on; the track and
        the arrows draw nothing."""
        handle = SurfaceHoverColour.rgb(self.renderer.scheme).hex
        self.setStyleSheet(
            "QScrollBar:vertical { background: transparent; margin: 0; border: none; }"
            f"QScrollBar::handle:vertical {{ background: {handle}; border-radius: {max(1, self.thickness // 2)}px;"
            " min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: none; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }")

    @classmethod
    def follow(cls, area: QAbstractScrollArea, clock: AnimationClock, renderer: QtLineRenderer,
               thickness: int) -> None:
        """Draw ``area``'s bar over its text ``thickness`` pixels wide while it moves; at 0
        the area has no overlay. The area's own bar is then sized by its column setting."""
        bar = area.findChild(cls, options=Qt.FindChildOption.FindDirectChildrenOnly)
        if bar is None:
            if not thickness:
                return
            bar = cls(area, clock, renderer)
        if bar.thickness != thickness:
            bar.thickness = thickness
            bar.paint_colours()
        if not thickness:
            bar.stop()
            bar.hide()
        else:
            bar.place()

    def stop(self) -> None:
        self.still.stop()
        if self.fade is not None:
            self.fade.animation.stop()
            self.fade = None

    def moved(self, value: int) -> None:
        """The area scrolled: show the bar at once at full strength and restart the wait."""
        self.setValue(value)
        if not self.thickness:
            return
        self.stop()
        self.opacity.setOpacity(1.0)
        self.setPageStep(self.source.pageStep())
        self.setSingleStep(self.source.singleStep())
        self.place()
        if self.maximum() > self.minimum():
            self.show()
            self.raise_()
        self.still.start()

    def fade_out(self) -> None:
        """Still long enough: fade, unless the reader is holding or pointing at the bar."""
        if self.isSliderDown() or self.underMouse():
            self.still.start()
            return
        if self.clock.enabled:
            self.fade = ScrollbarFade(self, self.clock)
        else:
            self.hide()

    def place(self) -> None:
        """Over the right edge of the viewport, its full height."""
        viewport = self.area.viewport().geometry()
        self.setGeometry(QRect(viewport.right() + 1 - self.thickness, viewport.top(),
                               self.thickness, viewport.height()))


class _ViewportGeometry(QObject):
    """Keeps the overlay over the viewport when the viewport is resized or moved."""

    def __init__(self, bar: OverlayScrollBar) -> None:
        super().__init__(bar)
        self.bar = bar

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move) and self.bar.thickness:
            self.bar.place()
        return False
