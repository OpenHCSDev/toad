"""Text drawn three rows tall in box-drawing glyphs, for a name read at a glance.

Textual's own 3x3 font (`textual.renderables.digits`) owns the digits, `A`-`F`
and a few signs; this module adds the letters and signs it lacks, in the same
light style. Lower case is drawn as upper case. A character neither table
has is drawn at normal size on the middle row.
"""

from __future__ import annotations

from typing import ClassVar

from rich.cells import cell_len
from textual.renderables.digits import DIGITS, DIGITS3X3

Glyph = tuple[str, str, str]


def _textual_glyphs() -> dict[str, Glyph]:
    """Textual's glyphs, each padded to its three-cell width."""
    return {
        character: tuple(row.ljust(3) for row in DIGITS3X3[index * 3 : index * 3 + 3])  # type: ignore[misc]
        for index, character in enumerate(DIGITS)
    }


class LargeText:
    """A line of text three rows tall, with a column between glyphs."""

    HEIGHT: ClassVar[int] = 3
    GLYPHS: ClassVar[dict[str, Glyph]] = {
        **_textual_glyphs(),
        "G": ("╭─╴", "│╶╮", "╰─╯"),
        "H": ("╷ ╷", "├─┤", "╵ ╵"),
        "I": ("╶┬╴", " │ ", "╶┴╴"),
        "J": ("  ╷", "  │", "╰─╯"),
        "K": ("╷╭╯", "├┤ ", "╵╰╮"),
        "L": ("╷  ", "│  ", "╰─╴"),
        "M": ("╭┬╮", "│││", "╵╵╵"),
        "N": ("╭─╮", "│ │", "╵ ╵"),
        "O": ("╭─╮", "│ │", "╰─╯"),
        "P": ("┌─╮", "├─╯", "╵  "),
        "Q": ("╭─╮", "│ │", "╰─╳"),
        "R": ("┌─╮", "├┬╯", "╵╰╴"),
        "S": ("╭─╴", "╰─╮", "╶─╯"),
        "T": ("╶┬╴", " │ ", " ╵ "),
        "U": ("╷ ╷", "│ │", "╰─╯"),
        "V": ("╷ ╷", "╲ ╱", " ╹ "),
        "W": ("╷ ╷", "│││", "╰┴╯"),
        "X": ("╲ ╱", " ╳ ", "╱ ╲"),
        "Y": ("╷ ╷", "╰┬╯", " ╵ "),
        "Z": ("╶─╮", " ╱ ", "╰─╴"),
        ".": (" ", " ", "•"),
        "·": (" ", "•", " "),
        "_": ("   ", "   ", "───"),
        "/": ("  ╱", " ╱ ", "╱  "),
        "#": ("╪╪", "╪╪", "  "),
    }

    @classmethod
    def glyph(cls, character: str) -> Glyph:
        return cls.GLYPHS.get(
            character.upper(),
            (" " * cell_len(character), character, " " * cell_len(character)),
        )

    @classmethod
    def rows(cls, text: str) -> tuple[str, ...]:
        glyphs = [cls.glyph(character) for character in text]
        return tuple(
            " ".join(glyph[row] for glyph in glyphs) for row in range(cls.HEIGHT)
        )

    @classmethod
    def width(cls, text: str) -> int:
        return cell_len(cls.rows(text)[0])
