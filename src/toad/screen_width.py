"""How wide the app's window is, and so how a window it opens is presented: one rule for
every frontend.

A width is counted in columns of the frontend's own text: a terminal's cells, or Qt's window
width over its font's average character width. A screen narrower than a hundred columns (a
phone, about fifty; a narrow terminal) is NARROW, and a window opened over the app fills it as
a phone app's page does. A wider one is WIDE: Textual draws the window as a side panel half the
screen wide, and Qt as a dialog floating over the app. Counting text, not pixels, makes the
rule the same on every display density: a phone's 412 device-independent pixels hold the same
fifty columns at any DPI.
"""

from __future__ import annotations

from enum import IntEnum


class ScreenWidth(IntEnum):
    """A screen's width class, from the fewest columns it starts at."""

    side_panel_percent: int | None
    """How much of a WIDE screen's width a side panel takes; None when a window fills it."""

    def __new__(cls, minimum_columns: int, side_panel_percent: int | None) -> ScreenWidth:
        mode = int.__new__(cls, minimum_columns)
        mode._value_ = minimum_columns
        mode.side_panel_percent = side_panel_percent
        return mode

    NARROW = (0, None)
    WIDE = (100, 50)

    @classmethod
    def of(cls, columns: float) -> ScreenWidth:
        """The class a screen `columns` wide is in: the widest one it reaches."""
        return max(mode for mode in cls if mode <= columns)
