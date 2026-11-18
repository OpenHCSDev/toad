"""F1 edits the same mode-qualified overrides used by native dispatch.

This screen is now a thin Textual renderer over `toad.client.keymap_browser.KeymapBrowserState`,
which owns the UX logic (filter, select, apply, reset) so Qt's `QtKeymapScreen` renders the
same data without re-implementing the logic.
"""
from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Input, Static
from toad.widgets.acting_button import ActingButton, DismissButton
from toad.widgets.checkbox import Checkbox

from toad.client.keymap_browser import KeymapBrowsing
from toad.keymap import KeyInvocationId
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
        self.query_ancestor(KeymapScreen).refresh_rows()


class KeymapApply(ActingButton):
    """Binds the typed keys to the selected actions."""

    async def act(self) -> None:
        await self.query_ancestor(KeymapScreen).apply_typed_keys()


class KeymapReset(ActingButton):
    """Returns the selected actions to their default keys."""

    async def act(self) -> None:
        await self.query_ancestor(KeymapScreen).reset_selected_keys()


class KeymapScreen(KeymapBrowsing, ShadedScreen, CenteredScreen, DismissibleScreen[None]):

    def __init__(self, focused: frozenset[KeyInvocationId]) -> None:
        super().__init__()
        self.begin_browsing(self.app, focused)

    def compose(self) -> ComposeResult:
        with KeymapPanel():
            yield Static(self.heading)
            yield KeymapSearch(placeholder=self.search_placeholder)
            yield Checkbox(self.focus_filter_label, value=True)
            yield KeymapTable(cursor_type="cell")
            yield KeymapSummary("", markup=False)
            with KeymapControls():
                yield KeymapKeys(placeholder=self.keys_placeholder)
                yield KeymapApply("Apply")
                yield KeymapReset("Reset")
                yield DismissButton("Close")
            yield KeymapStatus("", markup=False)

    @on(Mount)
    def on_mount(self) -> None:
        self.query_one(KeymapTable).add_columns("Action", *self.state.mode_labels())
        self.refresh_rows()

    @on(Checkbox.Changed)
    def focus_filter_changed(self) -> None:
        self.refresh_rows()

    @on(DataTable.CellSelected)
    def picked(self, message: DataTable.CellSelected) -> None:
        self.selection_changed()

    # The native reads and writes `KeymapBrowsing` asks for.

    def selected(self):
        row, column = self.query_one(KeymapTable).cursor_coordinate
        return self.state.select(row, column)

    def typed_keys(self) -> str:
        return self.query_one(KeymapKeys).value

    def search_text(self) -> str:
        return self.query_one(KeymapSearch).value

    def focus_filter_on(self) -> bool:
        return self.query_one(Checkbox).value

    def show_rows(self, rows) -> None:
        table = self.query_one(KeymapTable)
        table.clear()
        for row in rows:
            table.add_row(Text(row.title, style="dim" if row.dim else ""), *(
                Text(cell.keys, style="bold red" if cell.conflict else "") for cell in row.cells))

    def show_selection(self, keys: str, summary: str, conflicts: str) -> None:
        self.query_one(KeymapKeys).value = keys
        self.query_one(KeymapSummary).update(summary)
        self.query_one(KeymapStatus).update(conflicts)

    def show_status(self, text: str) -> None:
        self.query_one(KeymapStatus).update(text)

    def focus_keys(self) -> None:
        self.query_one(KeymapKeys).focus()

    def forget_selection(self) -> None:
        self.query_one(KeymapTable).move_cursor(row=0, column=0)
