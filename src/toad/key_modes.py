"""Saved profiles select an editing owner, not a handwritten command subset."""
from __future__ import annotations

from agent_comms.declared_choice import DeclaredChoice
from textual.document._editing import EditingMode, VimMode
from textual.keys import NavigationKey
from toad.neovim_editing import NeovimEditing


class KeyMode(EditingMode, DeclaredChoice, affix=""):
    """The saved preference selects native editing or a real Neovim initial state."""


class Standard(KeyMode):
    """Ordinary native text entry and navigation."""

    label = "STANDARD"


class VimInsert(NeovimEditing, KeyMode):
    """Start Neovim in Insert mode."""

    initial_keys = "i"
    map_modes = ("i",)

    @classmethod
    def navigation_spellings(cls, key: type[NavigationKey]) -> tuple[str, ...]:
        """Insert types its letters; only VimMode's modal spelling is an arrow there."""
        return super(VimMode, cls).navigation_spellings(key)


class VimNormal(NeovimEditing, KeyMode):
    """Start Neovim in Normal mode."""

    map_modes = ("n", "o")


class VimVisual(NeovimEditing, KeyMode):
    """Start Neovim in Visual mode."""

    initial_keys = "v"
    map_modes = ("x",)
