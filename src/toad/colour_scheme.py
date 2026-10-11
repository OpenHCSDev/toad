"""Colour meaning shared by every frontend: palettes, schemes, colours and depth.

A terminal palette is a terminal's sixteen ANSI colours with its default
foreground and background. A colour scheme names what each semantic colour is
(primary, warning, ...), with the terminal palette that ANSI output maps to.
Roles ask for a `ThemeColour`; each frontend resolves it from its active theme.
Colour depth is what the host terminal can show, decided once at launch.

Nothing here imports a terminal or rendering library.
"""

from __future__ import annotations

import curses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Self

from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import WireValue


@dataclass(frozen=True)
class Rgb(WireValue):
    """A 24-bit colour; its text form is `#rrggbb`."""

    red: int
    green: int
    blue: int

    @classmethod
    def from_wire(cls, data: Any) -> Self:
        if not (isinstance(data, str) and len(data) == 7 and data[0] == "#"):
            raise ValueError(f"Expected a #rrggbb colour, got {data!r}")
        value = int(data[1:], 16)
        return cls(value >> 16, (value >> 8) & 0xFF, value & 0xFF)

    def to_wire(self) -> str:
        return self.hex

    @property
    def hex(self) -> str:
        return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"

    @property
    def triple(self) -> tuple[int, int, int]:
        return self.red, self.green, self.blue

    @property
    def luminance(self) -> float:
        """Relative luminance (sRGB), 0 for black and 1 for white."""

        def linear(channel: int) -> float:
            value = channel / 255
            return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

        return 0.2126 * linear(self.red) + 0.7152 * linear(self.green) + 0.0722 * linear(self.blue)


@dataclass(frozen=True)
class TerminalPalette:
    """A terminal's colours: ANSI 0–15, the default foreground and background, the cursor."""

    background: Rgb
    foreground: Rgb
    cursor: Rgb
    ansi: tuple[Rgb, ...]

    def __post_init__(self) -> None:
        if len(self.ansi) != 16:
            raise ValueError(f"A terminal palette has 16 ANSI colours, not {len(self.ansi)}")

    @property
    def dark(self) -> bool:
        return self.background.luminance < 0.5

    def scheme(self, name: str) -> ColourScheme:
        """This palette as a scheme: each semantic colour is the ANSI slot ANSI themes use."""
        slot = self.ansi
        return ColourScheme(
            name=name, dark=self.dark, terminal=self,
            foreground=self.foreground, background=self.background,
            primary=slot[4], secondary=slot[6], accent=slot[5],
            success=slot[2], warning=slot[3], error=slot[1],
        )


@dataclass(frozen=True)
class ColourScheme:
    """What each semantic colour is in one theme, and the palette ANSI output maps to."""

    name: str
    dark: bool
    terminal: TerminalPalette
    foreground: Rgb
    background: Rgb
    primary: Rgb
    secondary: Rgb
    accent: Rgb
    success: Rgb
    warning: Rgb
    error: Rgb


def _palette(background: str, foreground: str, *ansi: str) -> TerminalPalette:
    return TerminalPalette(Rgb.from_wire(background), Rgb.from_wire(foreground),
                           Rgb.from_wire(foreground), tuple(map(Rgb.from_wire, ansi)))


# The palette ANSI colours map to under dark themes that bring no palette of their own.
DRACULA_PALETTE = _palette(
    "#282a36", "#f8f8f2",
    "#21222c", "#ff5555", "#50fa7b", "#f1fa8c", "#bd93f9", "#ff79c6", "#8be9fd", "#f8f8f2",
    "#6272a4", "#ff6e6e", "#69ff94", "#ffffa5", "#d6acff", "#ff92df", "#a4ffff", "#ffffff",
)


class ThemeColour(DeclaredFamily, affix="Colour"):
    """A semantic colour a role asks for; the active theme supplies it."""


class ForegroundColour(ThemeColour):
    """Ordinary text."""


class MutedColour(ForegroundColour):
    """Secondary text: the foreground, subdued."""


class PrimaryColour(ThemeColour):
    pass


class SecondaryColour(ThemeColour):
    pass


class AccentColour(ThemeColour):
    pass


class SuccessColour(ThemeColour):
    pass


class WarningColour(ThemeColour):
    pass


class ErrorColour(ThemeColour):
    pass


class ColourDepth(DeclaredFamily, affix="Depth"):
    """How many colours the host terminal shows; decided once, at launch.

    Painted rows keep their terminal sequences, so the depth cannot change
    while the app runs.
    """

    # The terminal-standard name (COLORTERM, Rich, Textual) for this depth.
    terminal_name: ClassVar[str]

    @staticmethod
    def of_terminal(environment: Mapping[str, str]) -> type[ColourDepth]:
        """The depth a terminal advertises: COLORTERM, then terminfo, then TERM's suffix."""
        if environment.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
            return TrueColourDepth
        term = environment.get("TERM", "")
        if not term or term in ("dumb", "unknown"):
            return Ansi16Depth
        try:
            curses.setupterm(term, -1)
        except curses.error:
            # No terminfo entry for TERM: the name is all the terminal said.
            pass
        else:
            if curses.tigetflag("Tc") == 1 or curses.tigetflag("RGB") == 1:
                return TrueColourDepth
            if curses.tigetnum("colors") >= 256:
                return Palette256Depth
        return Palette256Depth if term.endswith("256color") else Ansi16Depth


class TrueColourDepth(ColourDepth):
    terminal_name = "truecolor"


class Palette256Depth(ColourDepth):
    terminal_name = "256"


class Ansi16Depth(ColourDepth):
    terminal_name = "standard"
