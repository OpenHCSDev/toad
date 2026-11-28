"""Textual backend for ``formbridge.animation.FlashCoordinator`` over ``FormFlashSurface``."""

from __future__ import annotations

from collections.abc import Callable

from formbridge.animation.flash_coordinator import FlashCoordinator
from textual.color import Color
from textual.timer import Timer
from textual.widget import Widget
from ui_theme.scheme import PrimaryColour

from toad.client.form_flash import FormFlashSurface
from toad.textual_colours import ThemedApp


class TextualFlashSurface(FormFlashSurface):
    """Drives ``FlashCoordinator`` ticks on a Textual ``Widget`` and paints RGBA overlays."""

    def __init__(
        self,
        host: Widget,
        *,
        coordinator: FlashCoordinator | None = None,
    ) -> None:
        self._host = host
        self._timer: Timer | None = None
        super().__init__(coordinator=coordinator)

    def color_for_key(
        self, key: str, default_rgb: tuple[int, int, int]
    ) -> tuple[int, int, int]:
        del key
        if self._host.is_mounted and isinstance(self._host.app, ThemedApp):
            rgb = self._host.app.colours.colour(PrimaryColour)
            return (rgb.r, rgb.g, rgb.b)
        return default_rgb

    def schedule_tick(self, interval_ms: int, callback: Callable[[], None]) -> None:
        self.stop_tick()
        if not self._host.is_mounted:
            return
        self._timer = self._host.set_interval(max(0.008, interval_ms / 1000.0), callback)

    def stop_tick(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def target_visible(self, target: object) -> bool:
        return isinstance(target, Widget) and target.is_mounted and bool(target.display)

    def paint_target_rgba(
        self, target: object, rgba: tuple[int, int, int, int]
    ) -> None:
        if not isinstance(target, Widget) or not target.is_mounted:
            return
        red, green, blue, alpha = rgba
        target.styles.background = Color(red, green, blue, alpha / 255.0)

    def clear_target_flash(self, target: object) -> None:
        if not isinstance(target, Widget) or not target.is_mounted:
            return
        target.styles.background = None
