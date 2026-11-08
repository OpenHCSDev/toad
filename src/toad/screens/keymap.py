"""F1 edits the same mode-qualified overrides used by native dispatch."""
from __future__ import annotations

from collections.abc import Callable
from functools import partial
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Input, Static
from toad.widgets.acting_button import ActingButton, DismissButton
from toad.widgets.checkbox import Checkbox

from toad.key_modes import KeyMode
from toad.keymap import KeyInvocationId, Keymap, KeymapCatalog, KeymapRefused, KeymapRow, discover
from toad.preferences import SETTINGS
from toad.setting_declarations import FamilyChoices
from toad.native_style import AutoHeight, FillHeight, FillWidth, ScrollsVertically
from toad.screens.modal import CenteredScreen, DismissibleScreen, ModalPanel, ShadedScreen
from textual.events import Mount



class KeymapPanel(ScrollsVertically, ModalPanel):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = 1


class KeymapTable(FillHeight, DataTable):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.min_height = 3


class KeymapNote(AutoHeight, Static):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = 3


class KeymapSummary(KeymapNote):
    """The selected action's summary."""


class KeymapStatus(KeymapNote):
    """Conflicts and save results for the selected row."""


class KeymapControls(AutoHeight, Horizontal):
    """Its look is its bases."""


class KeymapKeys(FillWidth, Input):
    """Its look is its bases."""


class KeymapSearch(Input):
    """Filters the keymap's actions as its text changes.

    It handles its own Changed: KeymapSearch.Changed is Input.Changed, so a
    screen handler for it would also run when the keys field changes."""

    @on(Input.Changed)
    def searched(self, message: Input.Changed) -> None:
        message.stop()
        self.query_ancestor(KeymapScreen).populate(message.value)


class KeymapApply(ActingButton):
    """Binds the typed keys to the selected actions."""

    async def act(self) -> None:
        await self.query_ancestor(KeymapScreen).apply_keys()


class KeymapReset(ActingButton):
    """Returns the selected actions to their default keys."""

    async def act(self) -> None:
        await self.query_ancestor(KeymapScreen).reset_keys()


class KeymapScreen(ShadedScreen, CenteredScreen, DismissibleScreen[None]):

    def __init__(self, focused: frozenset[KeyInvocationId]) -> None:
        super().__init__()
        discover()
        self.focused_ids = focused
        self.mode_choices = FamilyChoices(KeyMode)
        self.modes = self.mode_choices.choices()
        self.catalog = KeymapCatalog.capture(self.modes)
        self.declarations = tuple(reference for reference, invocation
                                  in self.catalog.invocations.items()
                                  if not invocation.key_system())
        self.visible_declarations = self.declarations

    def compose(self) -> ComposeResult:
        with KeymapPanel():
            yield Static("Keyboard shortcuts — select a mode cell to change its keys")
            yield KeymapSearch(placeholder="Search actions")
            yield Checkbox("Only commands in the previous focus", value=True)
            yield KeymapTable(cursor_type="cell")
            yield KeymapSummary("", markup=False)
            with KeymapControls():
                yield KeymapKeys(placeholder="Keys separated by commas")
                yield KeymapApply("Apply")
                yield KeymapReset("Reset")
                yield DismissButton("Close")
            yield KeymapStatus("", markup=False)

    @on(Mount)
    def on_mount(self) -> None:
        table = self.query_one(KeymapTable)
        table.add_columns("Action", *(self.mode_choices.label(mode) for mode in self.modes))
        self.populate("")

    def populate(self, term: str) -> None:
        table = self.query_one(KeymapTable)
        table.clear()
        focused_only = self.query_one(Checkbox).value
        self.visible_declarations = tuple(declaration for declaration in self.declarations
                             if (not focused_only or self.catalog.require(declaration).visible_for_focus(
                                 declaration in self.focused_ids))
                             and term.casefold() in (self.catalog.require(declaration).key_title() + " "
                                                    + self.catalog.require(declaration).key_summary()).casefold())
        keymap = self.app.settings.ui.keymap
        conflicts = {row.binding_id for mode in self.modes for conflict in keymap.conflicts(mode)
                     for row in (conflict.first, conflict.second)}
        for declaration in self.visible_declarations:
            title = Text(self.catalog.require(declaration).key_title(),
                         style="" if self.catalog.require(declaration).visible_for_focus(
                             declaration in self.focused_ids) else "dim")
            table.add_row(title, *(Text(", ".join(self.catalog.effective(row, keymap)) or "—",
                                            style="bold red" if row.binding_id in conflicts else "")
                                   for mode in self.modes for row in (KeymapRow(declaration, mode),)))

    @on(Checkbox.Changed)
    def focus_filter_changed(self) -> None:
        self.populate(self.query_one(KeymapSearch).value)

    def selected_rows(self) -> tuple[KeymapRow, ...]:
        """The table cursor owns selection; no second selected row survives a filter change."""
        row, column = self.query_one(KeymapTable).cursor_coordinate
        if column and row < len(self.visible_declarations):
            selected = KeymapRow(self.visible_declarations[row], self.modes[column - 1])
            return (selected,) if self.catalog.defaults(selected) else ()
        return ()

    @on(DataTable.CellSelected)
    def picked(self, message: DataTable.CellSelected) -> None:
        for row in self.selected_rows():
            self.query_one(KeymapKeys).value = ", ".join(
                self.catalog.effective(row, self.app.settings.ui.keymap))
            self.query_one(KeymapSummary).update(
                self.catalog.require(row.declaration).key_summary())
            conflicts = tuple(conflict for conflict in self.app.settings.ui.keymap.conflicts(row.mode)
                              if row in (conflict.first, conflict.second))
            self.query_one(KeymapStatus).update("; ".join(map(str, conflicts)))
            self.query_one(KeymapKeys).focus()

    async def apply_keys(self) -> None:
        keys = self.query_one(KeymapKeys).value
        for row in self.selected_rows():
            normalized, = self.app._normalize_keymap({row.binding_id: keys}).values()
            await self.save(partial(Keymap.changed, row=row,
                                    keys=tuple(key for key in normalized.split(",") if key)))

    async def reset_keys(self) -> None:
        for row in self.selected_rows():
            await self.save(partial(Keymap.reset, row=row))

    async def save(self, edit: Callable[[Keymap], Keymap]) -> None:
        try:
            keymap = edit(self.app.settings.ui.keymap)
        except KeymapRefused as error:
            self.query_one(KeymapStatus).update(str(error))
            return
        self.app.saved_settings.set(SETTINGS.ui.keymap.bindings, keymap.bindings)
        await self.app.saved_settings.save()
        self.populate(self.query_one(KeymapSearch).value)
        self.query_one(KeymapStatus).update(
            "Not saved" if self.app.saved_settings.unsaved else "Saved")
