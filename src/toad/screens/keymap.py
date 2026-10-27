"""F1 edits the same mode-qualified overrides used by native dispatch."""
from __future__ import annotations

from collections.abc import Callable
from functools import partial
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.keys import KeyDeclaration
from textual.widgets import Button, Checkbox, DataTable, Input, Static
from textual.document._editing import EditingMode

from toad.key_modes import KeyMode
from toad.keymap import Keymap, KeymapRow, discover
from toad.preferences import SETTINGS
from toad.screens.modal import DismissibleScreen
from toad.widget_actions import DismissAction, System


class KeymapScreen(DismissibleScreen[None]):
    DEFAULT_CSS = """
    KeymapScreen { align: center middle; background: $background 40%; }
    KeymapScreen > Vertical {
        width: 95%; height: 95%; padding: 1;
        background: $surface; border: solid $primary;
    }
    KeymapScreen DataTable { height: 1fr; }
    KeymapScreen #keymap-summary { height: 3; }
    KeymapScreen #keymap-status { height: 3; }
    KeymapScreen Horizontal { height: auto; }
    KeymapScreen #keymap-keys { width: 1fr; }
    """

    def __init__(self, focus_mode: type[EditingMode], focused: frozenset[str]) -> None:
        super().__init__()
        discover()
        self.declarations = tuple(declaration for declaration in dict.fromkeys(KeyDeclaration.declarations())
                                  if not issubclass(declaration, System))
        self.focus_mode, self.focused_ids = focus_mode, focused
        self.modes = KeyMode.members_with(KeyMode)
        self.visible_declarations = self.declarations
        self.selected: KeymapRow | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Keyboard shortcuts — select a mode cell to change its keys")
            yield Input(placeholder="Search actions", id="keymap-search")
            yield Checkbox("Only commands in the previous focus", value=True, id="keymap-focused")
            yield DataTable(id="keymap-table", cursor_type="cell")
            yield Static("", id="keymap-summary", markup=False)
            with Horizontal():
                yield Input(placeholder="Keys separated by commas", id="keymap-keys")
                yield Button("Apply", id="keymap-apply")
                yield Button("Reset", id="keymap-reset")
                yield Button("Close", action=f"screen.{DismissAction.binding_name()}")
            yield Static("", id="keymap-status", markup=False)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Action", *(mode.choice_label() for mode in self.modes))
        self.populate("")

    def populate(self, term: str) -> None:
        table = self.query_one(DataTable)
        table.clear()
        focused_only = self.query_one("#keymap-focused", Checkbox).value
        self.visible_declarations = tuple(declaration for declaration in self.declarations
                             if (not focused_only or declaration.binding_id(self.focus_mode) in self.focused_ids)
                             and term.casefold() in (declaration.title + " " + declaration.summary()).casefold())
        keymap = self.app.settings.ui.keymap
        conflicts = {row.binding_id for mode in self.modes for conflict in keymap.conflicts(mode)
                     for row in (conflict.first, conflict.second)}
        for declaration in self.visible_declarations:
            title = Text(declaration.title,
                         style="" if declaration.binding_id(self.focus_mode) in self.focused_ids else "dim")
            table.add_row(title, *(Text(", ".join(row.effective(keymap)) or "—",
                                            style="bold red" if row.binding_id in conflicts else "")
                                   for mode in self.modes for row in (KeymapRow(declaration, mode),)))

    @on(Input.Changed, "#keymap-search")
    def searched(self, message: Input.Changed) -> None:
        self.populate(message.value)

    @on(Checkbox.Changed, "#keymap-focused")
    def focus_filter_changed(self) -> None:
        self.populate(self.query_one("#keymap-search", Input).value)

    @on(DataTable.CellSelected)
    def picked(self, message: DataTable.CellSelected) -> None:
        row, column = message.coordinate
        if not column:
            return
        self.selected = KeymapRow(self.visible_declarations[row], self.modes[column - 1])
        if not self.selected.defaults:
            self.selected = None
            self.query_one("#keymap-status", Static).update("This command has no key in that mode.")
            return
        self.query_one("#keymap-keys", Input).value = ", ".join(
            self.selected.effective(self.app.settings.ui.keymap))
        self.query_one("#keymap-summary", Static).update(self.selected.declaration.summary())
        conflicts = tuple(conflict for conflict in self.app.settings.ui.keymap.conflicts(self.selected.mode)
                          if self.selected in (conflict.first, conflict.second))
        self.query_one("#keymap-status", Static).update("; ".join(map(str, conflicts)))
        self.query_one("#keymap-keys", Input).focus()

    @on(Button.Pressed, "#keymap-apply")
    async def apply_keys(self) -> None:
        if self.selected is None:
            return
        keys = self.query_one("#keymap-keys", Input).value
        normalized = self.app._normalize_keymap({self.selected.binding_id: keys})
        await self.save(partial(Keymap.changed, row=self.selected,
                                keys=tuple(key for key in normalized[self.selected.binding_id].split(",") if key)))

    @on(Button.Pressed, "#keymap-reset")
    async def reset_keys(self) -> None:
        if self.selected is not None:
            await self.save(partial(Keymap.reset, row=self.selected))

    async def save(self, edit: Callable[[Keymap], Keymap]) -> None:
        try:
            keymap = edit(self.app.settings.ui.keymap)
        except ValueError as error:
            self.query_one("#keymap-status", Static).update(str(error))
            return
        self.app.saved_settings.set(SETTINGS.ui.keymap.bindings, keymap.bindings)
        await self.app.saved_settings.save()
        self.populate(self.query_one("#keymap-search", Input).value)
        self.query_one("#keymap-status", Static).update(
            "Not saved" if self.app.saved_settings.unsaved else "Saved")
