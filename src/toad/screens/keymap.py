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

from toad.client.keymap_browser import KeymapBrowserState
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
        self.state = KeymapBrowserState(self.app, focused)

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
        table.add_columns("Action", *self.state.mode_labels())
        self.populate("")

    def populate(self, term: str) -> None:
        self.state.set_search(term)
        self.state.set_focus_filter(self.query_one(Checkbox).value)
        table = self.query_one(KeymapTable)
        table.clear()
        for row in self.state.rows():
            title = Text(row.title, style="" if not row.dim else "dim")
            table.add_row(title, *(
                Text(cell.keys, style="bold red" if cell.conflict else "")
                for cell in row.cells
            ))

    @on(Checkbox.Changed)
    def focus_filter_changed(self) -> None:
        self.populate(self.query_one(KeymapSearch).value)

    def current_selection(self):
        """Resolve the cursor coordinate into a shared `KeymapSelection | None`."""
        row, column = self.query_one(KeymapTable).cursor_coordinate
        return self.state.select(row, column)

    @on(DataTable.CellSelected)
    def picked(self, message: DataTable.CellSelected) -> None:
        selection = self.current_selection()
        if selection is None:
            return
        self.query_one(KeymapKeys).value = self.state.current_keys(selection)
        self.query_one(KeymapSummary).update(self.state.summary(selection))
        self.query_one(KeymapStatus).update("; ".join(self.state.conflicts(selection)))
        self.query_one(KeymapKeys).focus()

    async def apply_keys(self) -> None:
        selection = self.current_selection()
        if selection is None:
            return
        result = await self.state.apply_keys(selection, self.query_one(KeymapKeys).value)
        self._show_result(result)

    async def reset_keys(self) -> None:
        selection = self.current_selection()
        if selection is None:
            return
        result = await self.state.reset_keys(selection)
        self._show_result(result)

    def _show_result(self, result) -> None:
        if result.should_repopulate():
            self.populate(self.query_one(KeymapSearch).value)
        self.query_one(KeymapStatus).update(result.status_text())
