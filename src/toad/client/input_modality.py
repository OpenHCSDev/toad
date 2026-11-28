"""How the reader drives this frontend, and what a menu row shows because of it.

A terminal is driven by keys, so its menu rows show each command's keys. A phone is driven by
touch: a key column there says nothing the reader can use, crowds the row, and a row must be
tall enough to tap. The frontend declares its modality; a menu asks it, never the window size.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar


class InputModality(ABC):
    """How the reader drives the frontend."""

    #: The least height a tappable row has, in device-independent pixels (0: its text's).
    row_height: ClassVar[int]
    #: Rows reserved for the horizontal tab-strip scrollbar when overflowing (1 on desktop, 0 on touch).
    tab_scrollbar_cells: ClassVar[int]
    #: Whether pointer hover highlights exist (True with mouse/keyboard; False on touch screens
    #: where Qt's synthesized pointer stays at the last tap point and sticks `:hover` forever).
    hover_highlights: ClassVar[bool]

    @classmethod
    def hover_rule(cls, rule: str) -> str:
        """Emit a QSS `:hover` rule only when this modality actually has a hovering pointer."""
        return rule if cls.hover_highlights else ""

    @classmethod
    def hover_or_pressed(cls, selector: str, body: str) -> str:
        """Style `:hover, :pressed` on pointer devices and `:pressed` alone on touch screens."""
        if cls.hover_highlights:
            return f"{selector}:hover, {selector}:pressed {{ {body} }}"
        return f"{selector}:pressed {{ {body} }}"

    @classmethod
    @abstractmethod
    def menu_keys(cls, keys: str) -> str:
        """The key column a menu row shows for a command bound to `keys`."""

    @classmethod
    @abstractmethod
    def row_text(cls, label: str, description: str) -> str:
        """Primary line of a menu row: label plus inline description when kept inline."""

    @classmethod
    @abstractmethod
    def row_subtext(cls, description: str) -> str:
        """Secondary line under a menu row's label when the description sits below it."""


class KeyboardInput(InputModality):
    """Driven by keys: rows show the keys that run them."""

    row_height = 0
    tab_scrollbar_cells = 1
    hover_highlights = True

    @classmethod
    def menu_keys(cls, keys: str) -> str:
        return keys

    @classmethod
    def row_text(cls, label: str, description: str) -> str:
        return f"{label} — {description}" if description else label

    @classmethod
    def row_subtext(cls, description: str) -> str:
        return ""


class TouchInput(InputModality):
    """Driven by touch: no key column; rows tall enough to tap (Android's 48dp target), the
    description on its own line under the label."""

    row_height = 48
    tab_scrollbar_cells = 0
    hover_highlights = False

    @classmethod
    def menu_keys(cls, keys: str) -> str:
        return ""

    @classmethod
    def row_text(cls, label: str, description: str) -> str:
        return label

    @classmethod
    def row_subtext(cls, description: str) -> str:
        return description
