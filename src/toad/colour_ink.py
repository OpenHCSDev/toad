"""Whether the app paints with the terminal's ANSI colours or with true colour.

Textual owns the fact (`App.native_ansi_color`: the theme's `ansi`, unless the
app overrides it); `ColourInk.of` decodes it once into a member, and every
consumer asks the member instead of branching on the flag or probing a
resolved colour's `.ansi`.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.style import Style
from textual.app import App
from textual.color import Color


@dataclass(frozen=True)
class ColourInk:
    """True colour: colours blend, muted text has its own colour, pills are filled.

    Members carry no fields: equal by kind, so a pickled copy keys the same prepared syntax.
    """

    fills_pills = True

    @classmethod
    def of(cls, app: App) -> ColourInk:
        """The boundary decoder: Textual's ANSI flag becomes a member here, once."""
        return ANSI_INK if app.native_ansi_color else TRUE_COLOUR_INK

    def choose[T](self, *, true_colour: T, ansi: T) -> T:
        """The consumer's declaration for this ink."""
        return true_colour

    def mixed(self, first: Color, last: Color, amount: float) -> Color:
        return first.blend(last, amount)

    def muted(self, muted: Color) -> Style:
        return Style(color=muted.rich_color)


@dataclass(frozen=True)
class AnsiInk(ColourInk):
    """The terminal's ANSI colours: they cannot blend, so they step; muted text is dim."""

    fills_pills = False

    def choose[T](self, *, true_colour: T, ansi: T) -> T:
        return ansi

    def mixed(self, first: Color, last: Color, amount: float) -> Color:
        return first if amount < 0.5 else last

    def muted(self, muted: Color) -> Style:
        return Style(dim=True)


TRUE_COLOUR_INK = ColourInk()
ANSI_INK = AnsiInk()
