"""Native Qt Vimium UI hint overlay backed by the shared `HintSessionState` family.

Every clickable Qt control inherits `QtHintTargetSource` (`HintTargetSource`) and yields its own
primary and/or contextual `HintTarget` instances — zero `isinstance` widget-type switches, zero
separate target registries. `QtHintOverlay` floats as a child of the window (never a top-level
`QWindow`, preserving Android EGL safety), paints crisp reverse-video labels using the active
theme's `BlockCursorBackgroundColour`/`BlockCursorForegroundColour`, and dispatches matched keys
polymorphically through `HintStep.apply(self)`.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import shiboken6
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from ui_theme.scheme import (
    BlockCursorBackgroundColour,
    BlockCursorForegroundColour,
    MutedColour,
)

from formbridge.hint_keys import HintLabelStyle, NextLetterHints
from toad.client.hints import (
    HintIntent,
    HintSessionState,
    HintTarget,
    HintTargetSource,
)
from toad.qt.lines import QtLineRenderer


@dataclass(frozen=True)
class QtCallbackHintTarget(HintTarget):
    """A live Qt hint target bound to a widget, a window-space anchor, and its original action."""

    widget: QWidget
    x: int
    y: int
    callback: Callable[[], object]

    def available(self) -> bool:
        return (
            shiboken6.isValid(self.widget)
            and self.widget.isVisible()
            and self.widget.isEnabled()
        )

    def activate(self) -> object:
        if not self.available():
            return None
        result = self.callback()
        if inspect.isawaitable(result):
            return asyncio.ensure_future(result)
        return result


class QtHintTargetSource(HintTargetSource):
    """Mixin for Qt controls that expose primary and/or contextual Vimium hint targets."""

    @staticmethod
    def hint_anchor(widget: QWidget, host: QWidget, local: QPoint | None = None) -> tuple[int, int]:
        point = QPoint(2, 2) if local is None else local
        mapped = widget.mapTo(host, point)
        return mapped.x(), mapped.y()


def collect_qt_hint_targets(host: QWidget, intent: HintIntent, *, exclude: QWidget | None = None) -> list[HintTarget]:
    """Walk visible descendants of `host`, skipping hidden subtrees and `exclude`, asking each
    `QtHintTargetSource` polymorphically for its targets under `intent`."""
    targets: list[HintTarget] = []
    host_rect = host.rect()

    def _walk(widget: QWidget) -> None:
        if widget is exclude or not shiboken6.isValid(widget) or not widget.isVisible():
            return
        if isinstance(widget, HintTargetSource):
            for target in intent.targets_of(widget, host):
                if (
                    target.available()
                    and 0 <= target.x < host_rect.width()
                    and 0 <= target.y < host_rect.height()
                ):
                    targets.append(target)
        for child in widget.children():
            if isinstance(child, QWidget):
                _walk(child)

    _walk(host)
    return targets


class QtHintOverlay(HintSessionState, QWidget, metaclass=PyQtWidgetMeta):
    """Transparent full-window overlay painting Vimium hint labels and capturing hint keys."""

    _original_focus: QWidget | None = None

    def __init__(self, host: QWidget, renderer: QtLineRenderer) -> None:
        super().__init__(host)
        self._host = host
        self._renderer = renderer
        self._original_focus: QWidget | None = None
        self.setObjectName("toad-hint-overlay")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()

    def open_for(self, intent: HintIntent, label_style: type[HintLabelStyle] = NextLetterHints) -> bool:
        """Collect live targets under `intent` and show hint badges; returns True if any exist."""
        self.dismiss_hints(restore=False)
        targets = collect_qt_hint_targets(self._host, intent, exclude=self)
        if not self.begin_session(targets, label_style):
            return False
        self._original_focus = self._host.focusWidget()
        self.setGeometry(self._host.rect())
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.update()
        return True

    def sync_geometry(self) -> None:
        if self.isVisible():
            self.setGeometry(self._host.rect())
            self.update()

    # ---- Polymorphic `HintStep` callbacks ----

    def hints_narrowed(self) -> None:
        self.update()

    def hint_matched(self, target: HintTarget) -> None:
        self.dismiss_hints(restore=True)
        target.activate()

    def dismiss_hints(self, *, restore: bool = True) -> None:
        was_visible = self.isVisible()
        original = self._original_focus
        self._original_focus = None
        self.clear_session()
        if was_visible:
            self.hide()
        if restore and original is not None and shiboken6.isValid(original) and original.isVisible():
            original.setFocus(Qt.FocusReason.OtherFocusReason)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if not self.isVisible():
            super().keyPressEvent(event)
            return
        key = event.key()
        event.accept()
        if key == Qt.Key.Key_Escape:
            self.dismiss_hints(restore=True)
            return
        if key == Qt.Key.Key_Backspace:
            self.backspace().apply(self)
            return
        text = event.text()
        if text and text.isprintable() and not (
            event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)
        ):
            self.feed_character(text).apply(self)
            return
        self.dismiss_hints(restore=True)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        event.accept()
        self.dismiss_hints(restore=True)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        super().focusOutEvent(event)
        if self.isVisible():
            self.dismiss_hints(restore=False)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        visible = self.visible_entries()
        if not visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont(self._host.font())
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        bg = QColor(self._renderer.theme(BlockCursorBackgroundColour))
        fg = QColor(self._renderer.theme(BlockCursorForegroundColour))
        typed_fg = QColor(self._renderer.theme(MutedColour))
        pad_x = 4
        badge_h = metrics.height() + 2
        max_x = max(0, self.width() - 4)
        max_y = max(0, self.height() - badge_h)
        for entry, text, typed in visible:
            label_w = metrics.horizontalAdvance(text) + pad_x * 2
            x = min(max(0, entry.target.x), max(0, max_x - label_w))
            y = min(max(0, entry.target.y), max_y)
            rect = QRect(x, y, label_w, badge_h)
            painter.setPen(QPen(fg, 1))
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 3, 3)
            baseline_y = y + metrics.ascent() + 1
            draw_x = x + pad_x
            if typed > 0:
                prefix_text = text[:typed]
                rest_text = text[typed:]
                painter.setPen(typed_fg)
                painter.drawText(draw_x, baseline_y, prefix_text)
                draw_x += metrics.horizontalAdvance(prefix_text)
                painter.setPen(fg)
                painter.drawText(draw_x, baseline_y, rest_text)
            else:
                painter.setPen(fg)
                painter.drawText(draw_x, baseline_y, text)
        painter.end()
