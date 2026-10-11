"""Animated effects, described once for every frontend.

An effect is a function of time: a frontend reads the clock when it paints, so
a skipped frame shows the right state on the next one. Nothing here imports a
terminal or rendering library.
"""

from __future__ import annotations

from dataclasses import dataclass

from toad.colour_scheme import AccentColour, PrimaryColour, SecondaryColour, ThemeColour


@dataclass(frozen=True)
class GradientSweep:
    """A band of theme colours moving across a row, one pass per period."""

    stops: tuple[type[ThemeColour], ...]
    period: float
    frames_per_second: float

    def shift(self, now: float, width: int) -> int:
        """How many cells the band has moved at `now`, from 0 to width − 1."""
        return int((now / self.period) % 1.0 * width)


# The busy indicator while an agent works.
ACTIVITY_SWEEP = GradientSweep((PrimaryColour, AccentColour, SecondaryColour),
                               period=1.0, frames_per_second=15)
