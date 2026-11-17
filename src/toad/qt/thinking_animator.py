"""One shared QTimer that pulses the foreground colour of every sidebar row whose
thread is currently working, mirroring Textual's `NAME_WAVE` effect on
`comms_sidebar.ThreadRow` (ui_theme.effects.NAME_WAVE). Textual runs the effect
per-row through its reactive animation loop; Qt has no equivalent, so one timer
on `QtToadApp` drives the pulse for every registered row and the sine phase is
shared across the whole sidebar.

Registration is replace-only: `set_working_items(items)` is called after each
sidebar redraw with the current set of working rows. Rows that fall out of the
set stop animating on the next tick; the timer turns itself off when the set is
empty so an idle sidebar costs nothing.
"""

from __future__ import annotations

import math
import time
import weakref
from typing import TYPE_CHECKING, Iterable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QBrush, QColor
from ui_theme.scheme import ColourScheme, ForegroundColour, PrimaryColour

if TYPE_CHECKING:
    from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class QtThinkingAnimator(QObject):
    """One shared animator per QtToadApp.

    The sine-phase pulse runs on wall time so two rows that start working at
    different ticks still share one visual wave — no per-row phase offset to
    track, which also matches Textual's `NAME_WAVE` where the effect's phase is
    the ribbon's clock, not the row's.
    """

    PERIOD_MS = 1600
    TICK_MS = 80

    def __init__(self, scheme: ColourScheme, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.scheme = scheme
        self._items: list[tuple[weakref.ref[QTreeWidgetItem], weakref.ref[QTreeWidget]]] = []
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._origin = time.monotonic()

    def set_working_items(self, items: Iterable["QTreeWidgetItem"]) -> None:
        """Replace the registered-working-row set with `items`. A row no longer in
        `items` reverts to its default foreground on the next redraw; this animator
        only paints items that are currently in its set."""
        fresh: list[tuple[weakref.ref, weakref.ref]] = []
        for item in items:
            tree = item.treeWidget()
            if tree is None:
                continue
            fresh.append((weakref.ref(item), weakref.ref(tree)))
        self._items = fresh
        if self._items:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        if not self._items:
            self._timer.stop()
            return
        base = ForegroundColour.rgb(self.scheme)
        accent = PrimaryColour.rgb(self.scheme)
        phase = (time.monotonic() - self._origin) * 1000.0 / self.PERIOD_MS
        amount = 0.5 * (1.0 + math.sin(2.0 * math.pi * phase))
        mix = base.blend(accent, amount)
        brush = QBrush(QColor(mix.hex))
        trees_to_update: set[QTreeWidget] = set()
        alive: list[tuple[weakref.ref, weakref.ref]] = []
        for item_ref, tree_ref in self._items:
            item = item_ref()
            tree = tree_ref()
            if item is None or tree is None:
                continue
            try:
                item.setForeground(0, brush)
            except RuntimeError:
                continue
            trees_to_update.add(tree)
            alive.append((item_ref, tree_ref))
        self._items = alive
        for tree in trees_to_update:
            viewport = tree.viewport()
            if viewport is not None:
                viewport.update()
