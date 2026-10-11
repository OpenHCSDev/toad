"""The Textual backend for colour schemes.

`toad.colour_scheme` says what the colours mean; this module renders that in
Textual: each scheme becomes a registered Textual theme, each theme's terminal
palette becomes the Rich terminal theme ANSI colours map to, the colour depth
becomes the console's colour system, and the line roles' colours become Rich
styles once per theme.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from rich.terminal_theme import TerminalTheme
from textual.theme import Theme
from watchdog.events import FileClosedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from toad.colour_scheme import DRACULA_PALETTE, ColourDepth, ColourScheme, TerminalPalette
from toad.wal_palette import WalFile
from toad.widgets.transcript_lines import LineTheme

if TYPE_CHECKING:
    from toad.app import ToadApp


def textual_theme(scheme: ColourScheme) -> Theme:
    return Theme(
        name=scheme.name, dark=scheme.dark,
        foreground=scheme.foreground.hex, background=scheme.background.hex,
        primary=scheme.primary.hex, secondary=scheme.secondary.hex, accent=scheme.accent.hex,
        success=scheme.success.hex, warning=scheme.warning.hex, error=scheme.error.hex,
    )


def rich_terminal_theme(palette: TerminalPalette) -> TerminalTheme:
    ansi = [colour.triple for colour in palette.ansi]
    return TerminalTheme(palette.background.triple, palette.foreground.triple, ansi[:8], ansi[8:])


class _WalFileClosed(FileSystemEventHandler):
    """pywal rewrites `colors.json` in place; it is whole once the writer closes it."""

    def __init__(self, colours: TextualColours) -> None:
        self.colours = colours

    def on_any_event(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileClosedEvent) and os.path.basename(event.src_path) == WalFile.NAME:
            self.colours.app.call_from_thread(self.colours.read_wal)


class TextualColours:
    """The app's colour depth, schemes, terminal palettes and line styles."""

    DARK_PALETTE = rich_terminal_theme(DRACULA_PALETTE)

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.depth: type[ColourDepth] = ColourDepth.of_terminal(os.environ)
        self.wal_directory = WalFile.directory(os.environ)
        # Set from the theme's CSS variables, which the app builds before it runs.
        self.line_theme: LineTheme
        self._terminal_themes: dict[str, TerminalTheme] = {}
        self._observer: Observer | None = None

    def start(self) -> None:
        """Register the pywal scheme, if pywal has written one, and follow its changes."""
        if not self.wal_directory.is_dir():
            return
        if (self.wal_directory / WalFile.NAME).is_file():
            self.read_wal()
        self._observer = Observer()
        self._observer.schedule(_WalFileClosed(self), str(self.wal_directory))
        self._observer.daemon = True
        self._observer.start()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer = None

    def read_wal(self) -> None:
        try:
            scheme = WalFile.read(self.wal_directory / WalFile.NAME).scheme
        except (OSError, ValueError, TypeError) as error:
            self.app.notify(f"pywal colours were not applied: {error}", title="Theme",
                            severity="error", timeout=10)
            return
        self.register(scheme)
        if self.app.theme == scheme.name:
            # Same theme name, new colours: apply the theme again.
            self.app.mutate_reactive(type(self.app).theme)

    def register(self, scheme: ColourScheme) -> None:
        self.app.register_theme(textual_theme(scheme))
        self._terminal_themes[scheme.name] = rich_terminal_theme(scheme.terminal)

    def terminal_theme(self, name: str) -> TerminalTheme:
        """The palette ANSI colours map to under a theme: its scheme's, else Toad's default."""
        theme = self._terminal_themes.get(name)
        if theme is None:
            dark = self.app.get_theme(name).dark
            theme = self._terminal_themes[name] = (
                self.DARK_PALETTE if dark else self.app.ansi_theme_light)
        return theme

    def variables_changed(self, variables: dict[str, str]) -> None:
        self.line_theme = LineTheme.of(variables)
