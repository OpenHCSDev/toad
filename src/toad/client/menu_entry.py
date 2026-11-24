"""The toolkit-neutral data a menu row renders: label, optional keyboard shortcut and
help text, and the action a selection runs.

Both Qt's `QtMenu` and Textual's `widgets/menu.Menu` consume this same shape, so a menu
is described in one place, by the family that owns the command, and rendered consistently
by whichever frontend is drawing it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from toad.client.input_modality import InputModality, KeyboardInput


@dataclass(frozen=True)
class MenuEntry:
    """One row in a menu: a bold keyboard shortcut (or empty), its label/description,
    and the action a selection runs. Qt's menu widget draws these fields as a two-column
    row; a plain-label menu passes `key_display=""`."""

    label: str
    run: Callable[[], object]
    key_display: str = ""
    description: str = ""


class MenuRowDisplay:
    """How a menu's rows show an entry's keys, label, and description under the frontend's
    declared `input_modality`. Shared by `BlockMenu` (`QtMenu`, Textual's `Menu`) and
    `ViewActionsPanel` (`QtViewActions`, Textual's `ViewActions`)."""

    input_modality: ClassVar[type[InputModality]] = KeyboardInput

    def row_keys(self, entry: MenuEntry) -> str:
        """The key column this menu's rows show for `entry`."""
        return self.input_modality.menu_keys(entry.key_display)

    def row_text(self, entry: MenuEntry) -> str:
        """A row's text column: the label, then its description on the same line when the
        modality keeps it inline; otherwise the description goes under the label."""
        return self.input_modality.row_text(entry.label, entry.description)

    def row_subtext(self, entry: MenuEntry) -> str:
        """The description line shown beneath a row's label when the modality stacks it."""
        return self.input_modality.row_subtext(entry.description)


def strip_menu_markup(description: str) -> str:
    """Textual menu descriptions carry `[u]`/`[/u]` tags for accelerator underlining; Qt's
    menu paints plain text, so the tags are stripped here. Shared with any other
    toolkit-neutral site that needs the plain label."""
    out: list[str] = []
    inside = False
    for char in description:
        if char == "[":
            inside = True
        elif char == "]":
            inside = False
        elif not inside:
            out.append(char)
    return "".join(out)
