"""F1 edits the same mode-qualified overrides used by native dispatch."""
from __future__ import annotations

from collections.abc import Callable
from functools import partial
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.keys import KeyInvocation
from textual.widgets import Button, Checkbox, DataTable, Input, Static
from textual.document._editing import EditingMode

from toad.key_modes import KeyMode
from toad.keymap import Keymap, KeymapCatalog, KeymapRefused, KeymapRow, discover
from toad.preferences import SETTINGS
from toad.setting_declarations import FamilyChoices
from toad.screens.modal import DismissibleScreen
from toad.widget_actions import DismissAction


class KeymapScreen(DismissibleScreen[None]):
    DEFAULT_CSS = """
    KeymapScreen { align: center middle; background: $background 40%; }
    KeymapScreen > Vertical {
        width: 95%; height: 95%; padding: 1;
        background: $surface; border: solid $primary; overflow-y: auto;
    }
    KeymapScreen DataTable { height: 1fr; min-height: 3; }
    KeymapScreen #keymap-summary, KeymapScreen #keymap-status {
        height: auto; max-height: 3;
    }
    KeymapScreen Horizontal { height: auto; }
    KeymapScreen #keymap-keys { width: 1fr; }
    """

    def __init__(self, focus_mode: type[EditingMode], focused: frozenset[str]) -> None:
        super().__init__()
        discover()
        self.focus_mode, self.focused_ids = focus_mode, focused
        self.mode_choices = FamilyChoices(KeyMode)
        self.modes = self.mode_choices.choices()
        self.catalog = KeymapCatalog.capture(self.modes)
        self.declarations = tuple(reference for reference, invocation
                                  in self.catalog.invocations.items()
                                  if not invocation.key_system())
        self.visible_declarations = self.declarations

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
        table.add_columns("Action", *(self.mode_choices.label(mode) for mode in self.modes))
        self.populate("")

    def populate(self, term: str) -> None:
        table = self.query_one(DataTable)
        table.clear()
        focused_only = self.query_one("#keymap-focused", Checkbox).value
        self.visible_declarations = tuple(declaration for declaration in self.declarations
                             if (not focused_only or KeyInvocation.in_mode(declaration, self.focus_mode) in self.focused_ids)
                             and term.casefold() in (self.catalog.require(declaration).key_title() + " "
                                                    + self.catalog.require(declaration).key_summary()).casefold())
        keymap = self.app.settings.ui.keymap
        conflicts = {row.binding_id for mode in self.modes for conflict in keymap.conflicts(mode)
                     for row in (conflict.first, conflict.second)}
        for declaration in self.visible_declarations:
            title = Text(self.catalog.require(declaration).key_title(),
                         style="" if KeyInvocation.in_mode(declaration, self.focus_mode) in self.focused_ids else "dim")
            table.add_row(title, *(Text(", ".join(self.catalog.effective(row, keymap)) or "—",
                                            style="bold red" if row.binding_id in conflicts else "")
                                   for mode in self.modes for row in (KeymapRow(declaration, mode),)))

    @on(Input.Changed, "#keymap-search")
    def searched(self, message: Input.Changed) -> None:
        self.populate(message.value)

    @on(Checkbox.Changed, "#keymap-focused")
    def focus_filter_changed(self) -> None:
        self.populate(self.query_one("#keymap-search", Input).value)

    def selected_rows(self) -> tuple[KeymapRow, ...]:
        """The table cursor owns selection; no second selected row survives a filter change."""
        row, column = self.query_one(DataTable).cursor_coordinate
        if column and row < len(self.visible_declarations):
            selected = KeymapRow(self.visible_declarations[row], self.modes[column - 1])
            return (selected,) if self.catalog.defaults(selected) else ()
        return ()

    @on(DataTable.CellSelected)
    def picked(self, message: DataTable.CellSelected) -> None:
        for row in self.selected_rows():
            self.query_one("#keymap-keys", Input).value = ", ".join(
                self.catalog.effective(row, self.app.settings.ui.keymap))
            self.query_one("#keymap-summary", Static).update(
                self.catalog.require(row.declaration).key_summary())
            conflicts = tuple(conflict for conflict in self.app.settings.ui.keymap.conflicts(row.mode)
                              if row in (conflict.first, conflict.second))
            self.query_one("#keymap-status", Static).update("; ".join(map(str, conflicts)))
            self.query_one("#keymap-keys", Input).focus()

    @on(Button.Pressed, "#keymap-apply")
    async def apply_keys(self) -> None:
        keys = self.query_one("#keymap-keys", Input).value
        for row in self.selected_rows():
            normalized, = self.app._normalize_keymap({row.binding_id: keys}).values()
            await self.save(partial(Keymap.changed, row=row,
                                    keys=tuple(key for key in normalized.split(",") if key)))

    @on(Button.Pressed, "#keymap-reset")
    async def reset_keys(self) -> None:
        for row in self.selected_rows():
            await self.save(partial(Keymap.reset, row=row))

    async def save(self, edit: Callable[[Keymap], Keymap]) -> None:
        try:
            keymap = edit(self.app.settings.ui.keymap)
        except KeymapRefused as error:
            self.query_one("#keymap-status", Static).update(str(error))
            return
        self.app.saved_settings.set(SETTINGS.ui.keymap.bindings, keymap.bindings)
        await self.app.saved_settings.save()
        self.populate(self.query_one("#keymap-search", Input).value)
        self.query_one("#keymap-status", Static).update(
            "Not saved" if self.app.saved_settings.unsaved else "Saved")
