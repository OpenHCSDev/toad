"""Qt backend for ``formbridge.animation.FlashCoordinator`` over ``FormFlashSurface``."""

from __future__ import annotations

from collections.abc import Callable

import shiboken6
from formbridge.animation.flash_coordinator import FlashCoordinator
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget
from ui_theme.scheme import PrimaryColour

from toad.client.form_flash import FormFlashSurface
from toad.qt.lines import QtLineRenderer


class QtFlashSurface(FormFlashSurface):
    """Drives ``FlashCoordinator`` ticks on a Qt ``QWidget`` host and paints RGBA tints."""

    def __init__(
        self,
        host: QWidget,
        *,
        renderer: QtLineRenderer | None = None,
        coordinator: FlashCoordinator | None = None,
    ) -> None:
        self._host = host
        self._renderer = renderer
        self._timer: QTimer | None = None
        self._callback: Callable[[], None] | None = None
        self._base_stylesheets: dict[int, str] = {}
        super().__init__(coordinator=coordinator)

    def set_renderer(self, renderer: QtLineRenderer) -> None:
        self._renderer = renderer

    def color_for_key(
        self, key: str, default_rgb: tuple[int, int, int]
    ) -> tuple[int, int, int]:
        del key
        if self._renderer is not None:
            color = QColor(self._renderer.theme(PrimaryColour))
            if color.isValid():
                return (color.red(), color.green(), color.blue())
        return default_rgb

    def schedule_tick(self, interval_ms: int, callback: Callable[[], None]) -> None:
        if not shiboken6.isValid(self._host):
            return
        if self._timer is None or not shiboken6.isValid(self._timer):
            self._timer = QTimer(self._host)
            self._callback = None
        else:
            self._timer.stop()
            if self._callback is not None:
                self._timer.timeout.disconnect(self._callback)
                self._callback = None
        self._timer.setInterval(max(8, int(interval_ms)))
        self._timer.timeout.connect(callback)
        self._callback = callback
        self._timer.start()

    def stop_tick(self) -> None:
        if self._timer is not None and shiboken6.isValid(self._timer):
            self._timer.stop()

    def target_visible(self, target: object) -> bool:
        return (
            isinstance(target, QWidget)
            and shiboken6.isValid(target)
            and target.isVisible()
        )

    def paint_target_rgba(
        self, target: object, rgba: tuple[int, int, int, int]
    ) -> None:
        if not isinstance(target, QWidget) or not shiboken6.isValid(target):
            return
        base = self._base_stylesheets.setdefault(id(target), target.styleSheet())
        red, green, blue, alpha = rgba
        tint = f"background-color: rgba({red}, {green}, {blue}, {alpha});"
        target.setStyleSheet(f"{base}\n{tint}" if base else tint)

    def clear_target_flash(self, target: object) -> None:
        base = self._base_stylesheets.pop(id(target), "")
        if not isinstance(target, QWidget) or not shiboken6.isValid(target):
            return
        target.setStyleSheet(base)
