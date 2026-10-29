"""Keyboard profiles compose the native editor modes; no second editor state."""
from __future__ import annotations

from agent_comms.declared_choice import DeclaredChoice
from textual.document._editing import (
    EditingMode,
    VimInsert as InsertEditing,
    VimMode as ModalEditing,
    VimNormal as NormalEditing,
    VimVisual as VisualEditing,
)

class KeyMode(EditingMode, DeclaredChoice, affix=""):
    """A preference selects the initial native mode, whose own transitions keep editing."""

class Standard(KeyMode):
    """Ordinary text entry and navigation."""

    label = "STANDARD"


class VimMode(KeyMode, ModalEditing):
    """The shared modal-key capability; the native key handler keeps this abstract."""


class VimInsert(VimMode, InsertEditing):
    """Start modal editing in Insert."""


class VimNormal(VimMode, NormalEditing):
    """Start modal editing in Normal."""


class VimVisual(VimNormal, VisualEditing):
    """Start modal editing in Visual."""
