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
