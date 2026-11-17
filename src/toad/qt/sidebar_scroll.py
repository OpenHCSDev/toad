"""Sidebar scroll-position indicator.

Textual's sidebar shows its vertical scroll position as a small percentage label
at the bottom edge (e.g. "36%"). Qt's `ConversationRows` had no equivalent, so the
viewer had no cue whether the visible channels/threads were the full set or only a
window into a longer list. This widget mirrors that percentage.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QLabel

from toad.qt.metrics import UiGap


class QtSidebarScrollIndicator(QLabel):
    """Bottom-right percentage overlay on a scroll area's viewport.

    Mirrors Textual's "N%" sidebar indicator. Hides when the content fits and
    nothing to scroll.
    """

    def __init__(self, scroll_area: QAbstractScrollArea) -> None:
        super().__init__(scroll_area.viewport())
        self._area = scroll_area
        self.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setContentsMargins(UiGap.tight, 0, UiGap.tight, 0)
        bar = scroll_area.verticalScrollBar()
        bar.valueChanged.connect(self._refresh)
        bar.rangeChanged.connect(self._refresh)
        scroll_area.viewport().installEventFilter(self)
        self._refresh()

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.Resize:
            self._reposition()
        return super().eventFilter(obj, event)

    def _refresh(self, *_args) -> None:
        bar = self._area.verticalScrollBar()
        span = bar.maximum() - bar.minimum()
        if span <= 0:
            self.hide()
            return
        pct = int(round((bar.value() - bar.minimum()) / span * 100))
        self.setText(f"{pct}%")
        self.show()
        self._reposition()

    def _reposition(self) -> None:
        viewport = self._area.viewport()
        self.adjustSize()
        x = viewport.width() - self.width() - UiGap.normal
        y = viewport.height() - self.height() - UiGap.normal
        self.move(max(0, x), max(0, y))
