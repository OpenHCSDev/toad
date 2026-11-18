"""How wide the app's window is, counted the same way by every frontend.

A width is counted in columns of the frontend's own text: a terminal's cells, or Qt's window
width over its font's average character width. Under a hundred columns (a phone holds about
fifty, a narrow terminal) is NARROW; wider is WIDE. Counting text, not pixels, makes the rule
the same at every display density: a phone's 412 device-independent pixels hold the same fifty
columns at any DPI. What each class means for a window opened over the app is
`toad.window_presentation`'s.
"""

from __future__ import annotations

from enum import IntEnum


class ScreenWidth(IntEnum):
    """A screen's width class; its value is the fewest columns it starts at."""

    NARROW = 0
    WIDE = 100

    @classmethod
    def of(cls, columns: float) -> ScreenWidth:
        """The class a screen `columns` wide is in: the widest one it reaches."""
        return max(mode for mode in cls if mode <= columns)
