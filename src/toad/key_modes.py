"""Saved profiles select an editing owner, not a handwritten command subset."""
from __future__ import annotations

from typing import ClassVar

from agent_comms.nominal.declared_choice import DeclaredChoice
from formbridge.key_declarations import ModalInputMode, NavigationKey
from textual.document._document import Selection
from textual.document._editing import EditingMode

from toad.neovim_editing import NeovimEditing


class KeyMode(EditingMode, DeclaredChoice, affix=""):
    """The saved preference selects native editing or a real Neovim initial state."""

    shows_badge: ClassVar[bool] = True

    def send_key(self, editor, key: str, character: str = "") -> bool:
        """Native standard editing lets the toolkit's own text widget consume keystrokes."""
        return False

    def dismiss_input(self, editor) -> None:
        """Escape with no popup open leaves the editor for its conversation window."""
        editor.leave_modal_editor()

    def set_text(self, editor, text: str) -> None:
        editor.set_native_text(text)

    def insert_text(self, editor, text: str) -> None:
        editor.insert_native_text(text)

    def clear_text(self, editor) -> None:
        editor.clear_native_text()

    def replace_span(self, editor, row: int, start: int, end: int, text: str) -> None:
        editor.replace_native_span(row, start, end, text)

    def engine_regions(self) -> tuple[Selection, ...]:
        """Visual selection regions reported by an attached modal engine (none in Standard)."""
        return ()


class Standard(KeyMode):
    """Ordinary native text entry and navigation."""

    label = "STANDARD"
    shows_badge = False


class VimInsert(NeovimEditing, KeyMode):
    """Start Neovim in Insert mode."""

    initial_keys = "i"
    map_modes = ("i",)

    @classmethod
    def navigation_spellings(cls, key: type[NavigationKey]) -> tuple[str, ...]:
        """Insert types its letters; only a modal input mode's spelling is an arrow there."""
        return super(ModalInputMode, cls).navigation_spellings(key)


class VimNormal(NeovimEditing, KeyMode):
    """Start Neovim in Normal mode."""

    map_modes = ("n", "o")


class VimVisual(NeovimEditing, KeyMode):
    """Start Neovim in Visual mode."""

    initial_keys = "v"
    map_modes = ("x",)
