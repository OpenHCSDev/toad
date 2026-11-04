"""Optional read-only view of the versioned Pi-package MCP inventory."""

from __future__ import annotations

from textual.worker import Worker
from pathlib import Path

from textual import containers, on
from textual.app import ComposeResult
from textual.css.native import Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles
from ui_theme.scheme import AccentColour
from toad.widgets.acting_button import ActingButton, DismissButton
from toad.native_style import AutoHeight
from toad.screens.modal import CenteredScreen, DismissibleScreen, SurfacePanel

from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from toad.mcp_commands import MCPDecision, MCPSelection
from toad.mcp_declarations import Declaration, Inventory
from toad.mcp_inventory import (
    read_inventory,
    render_inventory,
)


class MCPDecisionButton(ActingButton):
    """Opens its decision for the selected server."""

    def __init__(self, command: MCPDecision) -> None:
        super().__init__(command.label, disabled=True)
        self.command = command

    async def act(self) -> None:
        self.query_ancestor(MCPInventoryScreen).open_decision(self.command)


class RefreshInventory(ActingButton):
    """Reads the MCP inventory again."""

    async def act(self) -> None:
        self.query_ancestor(MCPInventoryScreen).action_refresh()


class InventoryPanel(SurfacePanel):
    native_theme = (NativeDeclaration.of(Styles.border, Keyword("round"), Variable(AccentColour.name)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = self.styles.height = "85%"
        self.styles.padding = (1, 2)


class InventoryStatus(Static):
    """The package's rendered inventory, or why it is unavailable."""


class InventoryRows(OptionList):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.height = 8


class InventoryButtons(AutoHeight, containers.Horizontal):
    """Its look is its bases."""


class MCPInventoryScreen(CenteredScreen, DismissibleScreen[None]):
    """The Pi package owns the inventory; this screen never owns decisions."""

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self.project_root = project_root
        self._read_task: Worker[None] | None = None
        self._generation = 0
        self._inventory: Inventory | None = None
        self._selected: Declaration | None = None

    def compose(self) -> ComposeResult:
        with InventoryPanel():
            with containers.VerticalScroll():
                yield InventoryStatus(
                    "Loading read-only Pi MCP package inventory…",
                    markup=False,
                )
            yield InventoryRows()
            with InventoryButtons():
                for member in MCPDecision.members_with(MCPDecision):
                    yield MCPDecisionButton(member())
            with InventoryButtons():
                yield RefreshInventory("Refresh")
                yield DismissButton("Close")

    def on_mount(self) -> None:
        self.action_refresh()

    def on_unmount(self) -> None:
        self._generation += 1
        if self._read_task is not None:
            self._read_task.cancel()

    def action_refresh(self) -> None:
        self._generation += 1
        if self._read_task is not None:
            self._read_task.cancel()
        self._inventory = None
        self._selected = None
        self.query_one(InventoryRows).clear_options()
        self._update_actions()
        self.query_one(InventoryStatus).update(
            "Loading read-only Pi MCP package inventory…"
        )
        self._read_task = self.run_worker(self._fetch(self._generation))

    async def _fetch(self, generation: int) -> None:
        # read_inventory owns the unavailable state (None) for its typed failures.
        inventory = await read_inventory(self.project_root)
        if generation == self._generation and self.is_attached:
            self._inventory = inventory
            self.query_one(InventoryStatus).update(
                render_inventory(inventory)
            )
            if inventory is not None:
                options = [
                    Option(
                        f"{row.scope.declared_name} / {row.id} · {row.status.declared_name}",
                        id=row.option_id,
                    )
                    for row in inventory.rows
                ]
                self.query_one(InventoryRows).add_options(options)

    def _selection(self) -> MCPSelection | None:
        if self._inventory is None or self._selected is None:
            return None
        return MCPSelection(self._inventory, self._selected)

    def _update_actions(self) -> None:
        selection = self._selection()
        for button in self.query(MCPDecisionButton):
            button.disabled = selection is None or not button.command.available(selection)

    @on(OptionList.OptionHighlighted)
    def on_row_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        snapshot = self._inventory
        self._selected = (
            next(
                (
                    row
                    for row in snapshot.rows
                    if row.option_id == event.option_id
                ),
                None,
            )
            if snapshot is not None
            else None
        )
        self._update_actions()

    def open_decision(self, command: MCPDecision) -> None:
        from toad.screens.mcp_decision import MCPDecisionScreen

        selection = self._selection()
        if selection is None:
            return
        self.app.push_screen(
            MCPDecisionScreen(selection, command),
            lambda _: self.action_refresh(),
        )
