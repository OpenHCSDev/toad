"""Shared spacing tokens for Qt widget layouts.

Before this module every setContentsMargins / setSpacing in the Qt tree carried
hand-rolled pixel numbers — the audit found 47 non-zero spacing calls across 18
files using 7 distinct values (2, 4, 6, 8, 10, 12, 24). Each value had a
meaning the raw number didn't carry: 4 for widget-internal grouping, 6 for row
padding, 8 for a panel's outer frame, 12 for a dialog's outer margin, and so
on.

Reading from `UiGap` instead gives every layout the same density vocabulary
and makes the whole frontend's density tunable from one place. Textual gets
the same tokens through its own CSS module; Qt consumes them as pixels.
"""

from __future__ import annotations

from enum import IntEnum

import shiboken6
from PySide6.QtWidgets import QLayout


def drain_layout_items(layout: QLayout, *, keep: int = 0) -> None:
    """Remove layout items down to ``keep`` trailing items and immediately release each
    ``QLayoutItem`` wrapper.

    ``QLayout.takeAt`` returns a non-``QObject`` ``QWidgetItem`` with C++ ownership
    (``ownedByPython == False``). Without ``shiboken6.delete(item)``, the C++ item leaks
    and stale wrapper addresses can collide with newly allocated ``QWidget`` instances
    (e.g. ``QListView.viewport()`` returning a stale ``QWidgetItem``).
    """
    while layout.count() > keep:
        item = layout.takeAt(0)
        if item is not None:
            shiboken6.delete(item)


def delete_layout_widgets(layout: QLayout, *, keep: int = 0) -> None:
    """Remove and schedule deletion of every widget in ``layout`` down to ``keep`` trailing
    items, immediately releasing each taken ``QLayoutItem`` from shiboken6."""
    while layout.count() > keep:
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        shiboken6.delete(item)


def scaled_px(base: int, percent: int, *, minimum: int = 1) -> int:
    """Scale a logical pixel measure ``base`` by UI zoom ``percent`` (50-200%)."""
    return max(minimum, round(base * percent / 100.0))


class UiGap(IntEnum):
    """Pixel-sized spacing tokens.

    tight  — inside-widget rhythm (list-item line-spacing, badge separation).
    normal — widget-internal padding, item grouping within a row.
    loose  — content padding for input rows and multi-item cells.
    frame  — outer padding of a panel / dialog content area.
    dialog — modal-dialog outer margin.
    page   — welcome / opening-view page margin.
    """

    tight = 2
    normal = 4
    loose = 6
    frame = 8
    wide = 10
    dialog = 12
    page = 24

    def scaled(self, percent: int) -> int:
        return scaled_px(int(self), percent, minimum=1 if self > 0 else 0)
