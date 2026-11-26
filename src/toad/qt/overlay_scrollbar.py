"""A scroll area's vertical bar drawn over its text while it moves (`Scrollbar.overlay`).

A bar beside the text takes its width for good; this one floats over the viewport's right
edge only while the area scrolls, and fades out a moment after it goes still. It mirrors the
area's own bar (hidden, still the model of the position), so dragging it scrolls the area and
any scroll of the area, by wheel, key, finger or code, shows it. Once faded it is hidden, so
it never takes a tap meant for the text under it.
"""

from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSlider, QScrollBar
from ui_theme.clock import AnimationClock
from ui_theme.scheme import BackgroundColour, SurfaceHoverColour

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
        self.bar.set_handle_opacity(amount)

    def land(self) -> None:
        self.bar.fade = None
        self.bar.hide()


class OverlayScrollBar(QScrollBar):
    """The overlay for one area; `follow` attaches it, or detaches it at width 0.

    Draws its rounded handle directly with `QPainter` instead of a permanent
    `QGraphicsOpacityEffect` + stylesheet: an opacity effect allocates an offscreen
    full-height pixmap and alpha-composites it on every scroll frame even at opacity 1.0."""

    STILL_MS = 1000
    """How long the area stays still before the bar fades."""

    def __init__(self, area: QAbstractScrollArea, clock: AnimationClock, renderer: QtLineRenderer, *,
                 watch_geometry: bool = True) -> None:
        super().__init__(Qt.Orientation.Vertical, area)
        # Opaque paint: fills its right-margin strip with BackgroundColour so updating the
        # moving thumb never walks up five ancestor widgets (QtHistoryWindow -> ConversationView
        # -> QStackedWidget -> QtWorkspaceChrome -> QtToadApp) painting backgrounds every frame.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.area, self.clock, self.renderer = area, clock, renderer
        self.source = area.verticalScrollBar()
        self.thickness = 0
        self.fade: ScrollbarFade | None = None
        self.handle_opacity = 1.0
        self._bg_color = QColor(BackgroundColour.rgb(renderer.scheme).hex)
        self._handle_color = QColor(SurfaceHoverColour.rgb(renderer.scheme).hex)
        self._last_thumb = QRect()
        self._last_moved = 0.0
        self.still = QTimer(self)
        self.still.setSingleShot(True)
        self.still.setInterval(self.STILL_MS)
        self.still.timeout.connect(self.fade_out)
        self.source.rangeChanged.connect(self.setRange)
        self.setRange(self.source.minimum(), self.source.maximum())
        self.source.valueChanged.connect(self.moved)
        self.valueChanged.connect(self.source.setValue)
        self.geometry_watch = _ViewportGeometry(self) if watch_geometry else None
        if self.geometry_watch is not None:
            area.viewport().installEventFilter(self.geometry_watch)
        renderer.themed(self, self.paint_colours)
        self.hide()

    def _thumb_rect(self) -> QRect:
        """Bounding rectangle of the rounded handle in this widget's coordinates."""
        span = self.maximum() - self.minimum()
        height = self.height()
        width = self.width()
        if span <= 0 or height <= 0 or width <= 0:
            return QRect()
        page = max(1, self.pageStep())
        thumb_h = max(24, min(height, round(height * page / (span + page))))
        top = round((self.value() - self.minimum()) / span * (height - thumb_h))
        return QRect(0, top, width, thumb_h)

    def _dirty_thumb(self) -> None:
        """Invalidate only the old and new handle rectangles instead of the full bar height."""
        new_thumb = self._thumb_rect()
        dirty = self._last_thumb.united(new_thumb) if not self._last_thumb.isEmpty() else new_thumb
        self._last_thumb = new_thumb
        if not dirty.isEmpty():
            self.update(dirty.adjusted(0, -1, 0, 1))

    def sliderChange(self, change: QAbstractSlider.SliderChange) -> None:  # type: ignore[override]
        """Avoid full-height `QWidget.update()` on scroll value changes so the backing-store
        dirty bounding box stays tight around the moving thumb instead of the whole viewport."""
        if change == QAbstractSlider.SliderChange.SliderValueChange:
            if self.isVisible():
                self._dirty_thumb()
            else:
                self._last_thumb = self._thumb_rect()
            return
        super().sliderChange(change)

    def set_handle_opacity(self, amount: float) -> None:
        if amount != self.handle_opacity:
            self.handle_opacity = amount
            thumb = self._thumb_rect()
            if not thumb.isEmpty():
                self.update(thumb.adjusted(0, -1, 0, 1))

    def paint_colours(self) -> None:
        """Cache the track background and raised handle colours; `paintEvent` draws both
        directly with `WA_OpaquePaintEvent`."""
        self._bg_color = QColor(BackgroundColour.rgb(self.renderer.scheme).hex)
        self._handle_color = QColor(SurfaceHoverColour.rgb(self.renderer.scheme).hex)
        if self.isVisible():
            self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(event.rect(), self._bg_color)
        if self.handle_opacity > 0.0:
            thumb = self._thumb_rect()
            if not thumb.isEmpty():
                self._last_thumb = thumb
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                if self.handle_opacity < 1.0:
                    painter.setOpacity(self.handle_opacity)
                radius = max(1.0, thumb.width() / 2.0)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._handle_color)
                painter.drawRoundedRect(thumb, radius, radius)
        painter.end()

    @classmethod
    def follow(cls, area: QAbstractScrollArea, clock: AnimationClock, renderer: QtLineRenderer,
               thickness: int, *, watch_geometry: bool = True) -> OverlayScrollBar | None:
        """Reserve ``thickness`` pixels on ``area``'s right viewport margin and draw the fading
        scrollbar in that strip so it never overlaps the viewport (overlapping siblings force
        `VirtualRowView.scrollContentsBy` to repaint the full-height right strip on every frame)."""
        bar = area.findChild(cls, options=Qt.FindChildOption.FindDirectChildrenOnly)
        if bar is None:
            if not thickness:
                return None
            bar = cls(area, clock, renderer, watch_geometry=watch_geometry)
        if bar.thickness != thickness:
            bar.thickness = thickness
            bar.paint_colours()
        margins = area.viewportMargins()
        if margins.right() != thickness:
            area.setViewportMargins(margins.left(), margins.top(), thickness, margins.bottom())
        if not thickness:
            bar.stop()
            bar.hide()
        else:
            bar.place()
        return bar

    def stop(self) -> None:
        self.still.stop()
        if self.fade is not None:
            self.fade.animation.stop()
            self.fade = None

    def moved(self, value: int) -> None:
        """The area scrolled: show the bar at once at full strength and schedule fade once still.

        Blocks signals around `setValue` so mirroring `source` never bounces `valueChanged` back
        into `source.setValue`, and records `_last_moved` instead of mutating Qt's C++ timer heap
        on every 90-120 Hz scroll tick."""
        if self.value() != value:
            self.blockSignals(True)
            try:
                self.setValue(value)
            finally:
                self.blockSignals(False)
        if not self.thickness:
            return
        self._last_moved = monotonic()
        if self.fade is not None:
            self.fade.animation.stop()
            self.fade = None
        if self.handle_opacity != 1.0:
            self.handle_opacity = 1.0
            self._dirty_thumb()
        page_step = self.source.pageStep()
        if self.pageStep() != page_step:
            self.setPageStep(page_step)
        single_step = self.source.singleStep()
        if self.singleStep() != single_step:
            self.setSingleStep(single_step)
        if self.maximum() > self.minimum() and not self.isVisible():
            self.place()
            self.show()
            self.raise_()
        if not self.still.isActive():
            self.still.start(self.STILL_MS)

    def fade_out(self) -> None:
        """Still long enough: fade, unless the reader is holding or pointing at the bar."""
        remaining_ms = round(self.STILL_MS - (monotonic() - self._last_moved) * 1000)
        if remaining_ms > 20:
            self.still.start(remaining_ms)
            return
        if self.isSliderDown() or self.underMouse():
            self.still.start(self.STILL_MS)
            return
        if self.clock.enabled:
            self.fade = ScrollbarFade(self, self.clock)
        else:
            self.hide()

    def place(self) -> None:
        """In the right viewport margin beside the viewport, its full height."""
        viewport = self.area.viewport().geometry()
        self.setGeometry(QRect(viewport.right() + 1, viewport.top(),
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
