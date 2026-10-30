"""Saved profiles select an editing owner, not a handwritten command subset."""
from __future__ import annotations

from agent_comms.declared_choice import DeclaredChoice
from textual.document._editing import EditingMode
from toad.neovim_editing import NeovimEditing


class KeyMode(EditingMode, DeclaredChoice, affix=""):
    """The saved preference selects native editing or a real Neovim initial state."""


class Standard(KeyMode):
    """Ordinary native text entry and navigation."""

    label = "STANDARD"


class VimInsert(NeovimEditing, KeyMode):
    """Start Neovim in Insert mode."""

    initial_keys = "i"


class VimNormal(NeovimEditing, KeyMode):
    """Start Neovim in Normal mode."""


class VimVisual(NeovimEditing, KeyMode):
    """Start Neovim in Visual mode."""

    initial_keys = "v"
