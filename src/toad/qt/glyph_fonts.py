"""The fonts Qt draws Toad's glyphs with, the same on a desktop and on Android.

Toad draws box drawing, block elements, braille, arrows and symbols (the multi-line message
symbol ☰, ✓, ❯, ⏎, the throbber and table rules) that the platform's text fonts lack. A
terminal finds them through its own fallback. Qt on Android does not: its fallback for a
family is a fixed per-family list, and the one Android font holding these glyphs (a subset of
Noto Sans Symbols) is on none of them, so they drew as nothing. The colour emoji font sat first
in Toad's own chain, so the symbols it does hold (↗, ⚠) drew orange.

The fonts here ship with Toad (`fonts/`, SIL OFL 1.1, subset to the blocks Toad draws) and
answer every such glyph, ahead of the emoji fonts, through one chain every Qt font inherits:
the application font's families, and the substitutes for each family a widget or rich text
asks for by name (`<pre>` asks for Courier New, the welcome banner for monospace).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

FONT_DIRECTORY = Path(__file__).with_name("fonts")

GLYPH_FONT_FILES = (
    "NotoSansMono-Regular.ttf",
    "NotoSansSymbols2-Regular.ttf",
    "NotoSansSymbols-Regular.ttf",
    "NotoSansMath-Regular.ttf",
)
"""In fallback order: the monospace face first, so box drawing and blocks keep one cell
width, then the symbol faces."""

MONOSPACE_FAMILY = "Noto Sans Mono"
"""The face Toad's cell grids draw in (the welcome banner), on every platform."""

EMOJI_FAMILIES = ("Noto Color Emoji", "Noto Emoji", "Twemoji", "Symbola")
"""After the glyph fonts: pictographs (a tool row's 🔧) only an emoji font holds. Android ships
Noto Color Emoji; a desktop has whichever of these is installed."""

NAMED_FAMILIES = (
    "monospace", "Monospace", "Courier New", "courier", "Courier", "Consolas",
    "Droid Sans Mono", "Cutive Mono", "Roboto", "sans-serif", "Arial",
)
"""Families Qt or a widget asks for by name: Qt's HTML `<pre>`/`<code>` (Courier New, courier),
QFont("monospace"), pyqt-reactive's widgets (Arial, Courier, Consolas) and Android's own faces.
Each falls back through the glyph chain before the emoji fonts, as does each glyph family itself
(the banner asks for Noto Sans Mono by name)."""


def install_glyph_fonts(application: QApplication) -> tuple[str, ...]:
    """Register the bundled fonts and put them in every Qt font's fallback chain, ahead of the
    emoji fonts. Returns the glyph families in fallback order."""
    glyph_families = tuple(family for file in GLYPH_FONT_FILES for family in _registered(FONT_DIRECTORY / file))
    chain = [*glyph_families, *EMOJI_FAMILIES]
    font = application.font()
    font.setFamilies([font.family(), *chain])
    application.setFont(font)
    for family in (*NAMED_FAMILIES, font.family(), *glyph_families):
        QFont.insertSubstitutions(family, [fallback for fallback in chain if fallback != family])
    return glyph_families


def _registered(path: Path) -> list[str]:
    """The families a bundled font file adds; a file Qt cannot load stops the start, since every
    glyph it answers would otherwise draw as nothing again."""
    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        raise RuntimeError(f"Qt could not load the bundled font {path}")
    return QFontDatabase.applicationFontFamilies(font_id)
