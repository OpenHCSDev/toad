"""Unified 160 ms text-inversion tap feedback for all clickable Qt text buttons and labels.

Instead of scattering per-widget `QToolButton { color: ...; border: none; padding: ... }`
stylesheets and `:pressed` grey-box hacks across 15 modules, every flat text button,
disclosure, goal action, sort control, queue link, and push button inherits `TapFlashControl`
(`QtTextButton` / `QtPushButton`) and inverts its own live theme ink against background on
tap — matching message header and link inversion (`TapHighlight`).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import QPushButton, QToolButton
from ui_theme.scheme import BackgroundColour, ThemeColour

from toad.client.tap_flash import TapFeedback
from toad.qt.lines import QtLineRenderer


class TapFlashControl(TapFeedback):
    """Mixin giving any Qt text button or label a 160 ms ink/background inversion flash on tap."""

    _tap_flashing: bool = False
    _tap_flash_timer: QTimer | None = None
    _tap_flash_renderer: QtLineRenderer | None = None
    _tap_flash_ink: type[ThemeColour] | None = None
    _tap_flash_underline: bool = False
    _tap_flash_left_align: bool = False
    _tap_flash_pad_x: int = 0

    def bind_tap_ink(
        self,
        renderer: QtLineRenderer,
        ink: type[ThemeColour],
        *,
        underline: bool = False,
        left_align: bool = False,
        pad_x: int = 0,
    ) -> None:
        """Bind the live renderer and theme colour this control draws in so tap inversion
        always tracks theme switches without duplicating hex strings."""
        self._tap_flash_renderer = renderer
        self._tap_flash_ink = ink
        self._tap_flash_underline = underline
        self._tap_flash_left_align = left_align
        self._tap_flash_pad_x = pad_x

    def tap_flash_colours(self) -> tuple[QColor, QColor]:
        """Return `(background, ink)` for this control under the current theme."""
        renderer = self._tap_flash_renderer
        ink_colour = self._tap_flash_ink
        if renderer is not None and ink_colour is not None:
            return (
                QColor(renderer.theme(BackgroundColour)),
                QColor(renderer.theme(ink_colour)),
            )
        palette = self.palette()
        bg = palette.color(QPalette.ColorRole.Window)
        ink = palette.color(QPalette.ColorRole.ButtonText)
        if not ink.isValid() or ink == bg:
            ink = palette.color(QPalette.ColorRole.WindowText)
        return bg, ink

    def tap_flash_text_flags(self) -> int:
        """Alignment/wrapping flags used when drawing the inverted label text."""
        if self._tap_flash_left_align:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return int(Qt.AlignmentFlag.AlignCenter)

    def flash_tap(self) -> None:
        """Trigger or extend the 160 ms inverted-ink flash."""
        self._tap_flashing = True
        timer = self._tap_flash_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(self.tap_flash_duration_ms)
            timer.timeout.connect(self._end_tap_flash)
            self._tap_flash_timer = timer
        timer.start()
        self.update()

    def _end_tap_flash(self) -> None:
        if not self._tap_flashing:
            return
        self._tap_flashing = False
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.flash_tap()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if not self._tap_flashing:
            super().paintEvent(event)
            return
        bg, ink = self.tap_flash_colours()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        painter.drawRoundedRect(QRectF(self.rect()), 3.0, 3.0)
        font = QFont(self.font())
        if self._tap_flash_underline:
            font.setUnderline(True)
        painter.setFont(font)
        painter.setPen(bg)
        pad = self._tap_flash_pad_x
        text_rect = self.contentsRect().adjusted(pad, 0, -pad, 0)
        painter.drawText(text_rect, self.tap_flash_text_flags(), self.text())
        painter.end()


class QtTextButton(TapFlashControl, QToolButton):
    """Single flat text-button owner across Qt: owns both its flat themed stylesheet and
    its 160 ms inverted-ink tap flash."""

    def apply_text_style(
        self,
        renderer: QtLineRenderer,
        ink: type[ThemeColour],
        *,
        underline: bool = False,
        left_align: bool = False,
        pad_x: int = 0,
    ) -> None:
        self.bind_tap_ink(renderer, ink, underline=underline, left_align=left_align, pad_x=pad_x)
        parts = [
            f"color: {renderer.theme(ink)}",
            "background-color: transparent",
            "border: none",
            f"padding: 0 {pad_x}px" if pad_x else "padding: 0",
        ]
        if underline:
            parts.append("text-decoration: underline")
        if left_align:
            parts.append("text-align: left")
        renderer.apply_sheet(self, f"QToolButton {{ {'; '.join(parts)}; }}")


class QtPushButton(TapFlashControl, QPushButton):
    """Clickable `QPushButton` inheriting the shared 160 ms text-inversion tap flash."""
