"""The Textual backend for ui_theme's schemes and effects.

`ui_theme` says what the colours and effects mean; this module draws that in
Textual: each scheme becomes a registered Textual theme, each scheme's terminal
palette becomes the Rich terminal theme ANSI colours map to, the colour depth
becomes the console's colour system, the line roles' colours become Rich styles
once per theme, effect frames become strips, and the animation clock runs on
one Textual timer.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.terminal_theme import TerminalTheme
from textual.color import Color
from textual.strip import Strip
from textual.theme import Theme
from textual.timer import Timer
from watchdog.events import FileClosedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ui_theme.backend import Backend, TerminalBackend
from ui_theme.catalog import SCHEMES
from ui_theme.clock import AnimationClock
from ui_theme.colour import AnsiColour, Rgb, TerminalPalette
from ui_theme.depth import ColourDepth
from ui_theme.effects import Band, Gradient, Mix, TextFrame
from ui_theme.scheme import ColourScheme, LayerColour, ThemeColour, CoreColour, TextStyle
from ui_theme.wal import WalFile
from toad.widgets.transcript_lines import LineTheme

if TYPE_CHECKING:
    from toad.app import ToadApp


class _WalFileClosed(FileSystemEventHandler):
    """pywal rewrites `colors.json` in place; it is whole once the writer closes it."""

    def __init__(self, colours: TextualColours) -> None:
        self.colours = colours

    def on_any_event(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileClosedEvent) and os.path.basename(event.src_path) == WalFile.NAME:
            self.colours.app.call_from_thread(self.colours.read_wal)


def _element(value: Any, backend: TextualColours) -> str:
    return value.value if isinstance(value, TextStyle) else value.native(backend)


class TextualColours(Backend[Theme, Color, Any, Strip], TerminalBackend[TerminalTheme]):
    """The app's colour depth, schemes, terminal palettes, line styles and animation clock."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.depth: type[ColourDepth] = ColourDepth.of_terminal(os.environ)
        self.wal_directory = WalFile.directory(os.environ)
        # Set from the theme's CSS variables, which the app builds before it runs.
        self.line_theme: LineTheme
        self.variables: dict[str, str] = {}
        self.schemes: dict[str, ColourScheme] = {}
        # Textual asks for the terminal palette before themes can be registered.
        self._terminal_themes: dict[str, TerminalTheme] = {}
        for scheme in SCHEMES:
            self._add(scheme)
        self._observer: Observer | None = None
        self._timer: Timer | None = None
        self.clock = AnimationClock(self._schedule)

    # The catalog and pywal.

    def register_catalog(self) -> None:
        """Offer ui_theme's schemes, replacing Textual's copies of the same themes."""
        for scheme in self.schemes.values():
            self.app.register_theme(self.theme(scheme))
        if (self.wal_directory / WalFile.NAME).is_file():
            self.read_wal()

    def start(self) -> None:
        """Follow pywal's changes to its palette."""
        self.clock.enabled = self.app.animation_level != "none"
        if not self.wal_directory.is_dir():
            return
        self._observer = Observer()
        self._observer.schedule(_WalFileClosed(self), str(self.wal_directory))
        self._observer.daemon = True
        self._observer.start()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer = None
        self._schedule(None)

    def read_wal(self) -> None:
        try:
            scheme = WalFile.read(self.wal_directory / WalFile.NAME).scheme
        except (OSError, ValueError) as error:
            self.app.notify(f"pywal colours were not applied: {error}", title="Theme",
                            severity="error", timeout=10)
            return
        self.register(scheme)
        if self.app.is_running and self.app.theme == scheme.name:
            # Same theme name, new colours: apply the theme again.
            self.app.mutate_reactive(type(self.app).theme)

    def register(self, scheme: ColourScheme) -> None:
        self._add(scheme)
        self.app.register_theme(self.theme(scheme))

    def _add(self, scheme: ColourScheme) -> None:
        self.schemes[scheme.name] = scheme
        self._terminal_themes[scheme.name] = self.palette(scheme.terminal)

    def choose(self, name: str) -> None:
        if name not in self.schemes:
            # `wal` exists once pywal has written its palette.
            self.app.notify(f"Theme {name!r} is not available"
                            + (f": pywal has not written {self.wal_directory / WalFile.NAME}"
                               if name == WalFile.SCHEME else ""),
                            title="Theme", severity="error", timeout=10)
            return
        self.app.theme = name

    @property
    def scheme(self) -> ColourScheme:
        return self.schemes[self.app.theme]

    def terminal_theme(self, name: str) -> TerminalTheme:
        """The palette ANSI colours map to under a theme."""
        return self._terminal_themes[name]

    def variables_changed(self, variables: dict[str, str]) -> None:
        self.variables = variables
        self.line_theme = LineTheme.of(variables)
        _row.cache_clear()

    # The backend.

    def theme(self, scheme: ColourScheme) -> Theme:
        colours = {colour.name: value.native(self) for colour, value in scheme.colours.items()
                   if issubclass(colour, (CoreColour, LayerColour))}
        return Theme(name=scheme.name, dark=scheme.dark, ansi=scheme.from_terminal,
                     variables={name: _element(value, self) for name, value in scheme.elements.items()},
                     **colours)

    def palette(self, palette: TerminalPalette) -> TerminalTheme:
        ansi = [colour.triple for colour in palette.ansi]
        return TerminalTheme(palette.background.triple, palette.foreground.triple, ansi[:8], ansi[8:])

    def rgb(self, colour: Rgb) -> str:
        if colour.alpha == 1:
            return colour.hex
        # Textual reads alpha exactly as #rrggbbaa or as a percentage.
        byte = colour.alpha * 255
        return (f"{colour.hex}{round(byte):02x}" if abs(byte - round(byte)) < 1e-6
                else f"{colour.hex} {colour.alpha * 100:g}%")

    def ansi(self, colour: AnsiColour) -> str:
        return f"ansi_{colour.name}"

    def terminal_default(self) -> str:
        return "ansi_default"

    def colour(self, colour: type[ThemeColour]) -> Color:
        """A theme colour as the current CSS variables make it."""
        return Color.parse(self.variables[colour.name])

    def mixed(self, start: type[ThemeColour], end: type[ThemeColour], amount: float) -> Color:
        first, last = self.colour(start), self.colour(end)
        # Terminal colours cannot be blended; they step.
        if first.ansi is not None or last.ansi is not None:
            return first if amount < 0.5 else last
        return first.blend(last, amount)

    def paint_gradient(self, frame: Gradient, target: Strip) -> Strip:
        """A uniform row (one glyph, one style) in the gradient; the row is built once per width."""
        width = target.cell_length
        first = next(iter(target))
        row = _row(self, frame.stops, width, first.text[:1], first.style)
        start = width - int(frame.offset * width) % max(width, 1)
        return Strip(row[start:start + width], cell_length=width)

    def paint_mix(self, frame: Mix, target: Strip) -> Strip:
        return target.apply_style(RichStyle(color=self.mixed(frame.start, frame.end, frame.amount).rich_color))

    def paint_band(self, frame: Band, target: Strip) -> Strip:
        width = target.cell_length
        start, end = (max(0, min(width, round(edge * width))) for edge in (frame.start, frame.end))
        if start >= end:
            return target
        before, band, after = target.divide((start, end, width))
        band = band.apply_style(RichStyle(color=self.colour(frame.colour).rich_color))
        return Strip.join((before, band, after))

    def paint_text(self, frame: TextFrame, target: Strip) -> list[Strip]:
        base = next(iter(target)).style if target.cell_length else None
        return [Strip([Segment(character, base + RichStyle(color=colour.hex) if base else
                               RichStyle(color=colour.hex)) if colour else Segment(character, base)
                       for character, colour in line]) for line in frame.lines]

    # The animation clock's one timer.

    def _schedule(self, interval: float | None) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if interval is not None:
            self._timer = self.app.set_interval(interval, self.clock.tick, name="animation clock")


@lru_cache(maxsize=16)
def _row(colours: TextualColours, stops: tuple[type[ThemeColour], ...], width: int,
         character: str, style: RichStyle | None) -> list[Segment]:
    """Two widths of a gradient, so any window of `width` cells is a slice."""
    frame = Gradient(stops, 0.0)
    background = style.bgcolor if style is not None else None
    segments = []
    for cell in range(width * 2):
        start, end, amount = frame.at(cell / max(width, 1))
        colour = colours.mixed(start, end, amount)
        segments.append(Segment(character, RichStyle.from_color(colour.rich_color, background)))
    return segments
