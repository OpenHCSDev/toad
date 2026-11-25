"""Saved profiles select an editing owner, not a handwritten command subset."""
from __future__ import annotations

from typing import ClassVar

from agent_comms.nominal.declared_choice import DeclaredChoice
from formbridge.key_declarations import ModalInputMode, NavigationKey
from textual.document._editing import EditingMode

from toad.neovim_editing import InsertState, NeovimEditing, NeovimState, NormalState


class KeyMode(EditingMode, DeclaredChoice, affix=""):
    """The saved preference selects native editing or a real Neovim initial state."""

    shows_badge: ClassVar[bool] = True


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


class ModalEditingState(ModalInputMode):
    """Stateful modal input mode backed by the shared `NeovimState` family."""

    shows_badge: ClassVar[bool] = True

    def __init__(self, key_mode: type[KeyMode]) -> None:
        self.state: NeovimState = NeovimState.for_mode(key_mode.map_modes[0])(blocking=False)

    @property
    def label(self) -> str:
        return self.state.label

    @property
    def accepts_text(self) -> bool:
        """The shared `EditingMode.accepts_text`, answered by the current Neovim state."""
        return self.state.accepts_text

    def enter_insert(self) -> None:
        self.state = InsertState(blocking=False)

    def enter_normal(self) -> None:
        self.state = NormalState(blocking=False)
