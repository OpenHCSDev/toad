"""The toolkit-neutral data a menu row renders: label, optional keyboard shortcut and
help text, and the action a selection runs.

Both Qt's `QtMenu` and Textual's `widgets/menu.Menu` consume this same shape, so a menu
is described in one place, by the family that owns the command, and rendered consistently
by whichever frontend is drawing it. `OfferedAction` remains for callers that only have a
label and a run (bus-row long-press menus, for example): they make a `MenuEntry` with
empty `key_display` and `description` through `MenuEntry.from_offered`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from toad.client.offered_action import OfferedAction


@dataclass(frozen=True)
class MenuEntry:
    """One row in a menu: a bold keyboard shortcut (or empty), its label/description,
    and the action a selection runs. Qt's menu widget draws these fields as a two-column
    row; a plain-label menu passes `key_display=""`."""

    label: str
    run: Callable[[], object]
    key_display: str = ""
    description: str = ""

    @classmethod
    def from_offered(cls, action: OfferedAction) -> MenuEntry:
        """Legacy adaptor: an OfferedAction has only label + run, so the row renders
        with no keyboard-shortcut column and no second description line."""
        return cls(label=action.label, run=action.run)


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
