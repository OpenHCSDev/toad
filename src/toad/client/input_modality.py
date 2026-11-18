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

    @classmethod
    @abstractmethod
    def menu_keys(cls, keys: str) -> str:
        """The key column a menu row shows for a command bound to `keys`."""

    @classmethod
    @abstractmethod
    def describes_inline(cls) -> bool:
        """Whether a row's description follows its label on the same line."""


class KeyboardInput(InputModality):
    """Driven by keys: rows show the keys that run them."""

    row_height = 0

    @classmethod
    def menu_keys(cls, keys: str) -> str:
        return keys

    @classmethod
    def describes_inline(cls) -> bool:
        return True


class TouchInput(InputModality):
    """Driven by touch: no key column; rows tall enough to tap (Android's 48dp target), the
    description on its own line under the label."""

    row_height = 48

    @classmethod
    def menu_keys(cls, keys: str) -> str:
        return ""

    @classmethod
    def describes_inline(cls) -> bool:
        return False
