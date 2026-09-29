"""Optional read-only view of the versioned Pi-package MCP inventory."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from textual import containers, on
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from toad.mcp_commands import MCPDecision, MCPSelection
from toad.mcp_declarations import Declaration, Inventory
from toad.mcp_inventory import (
    read_inventory,
    render_inventory,
)


class MCPDecisionButton(Button):
    def __init__(self, command: MCPDecision) -> None:
        super().__init__(command.label, id=command.button_id, disabled=True)
        self.command = command


class MCPInventoryScreen(ModalScreen[None]):
    """The Pi package owns the inventory; this screen never owns decisions."""

    DEFAULT_CSS = """
    MCPInventoryScreen { align: center middle; }
    MCPInventoryScreen #mcp-inventory-panel {
        width: 85%; height: 85%; border: round $accent; background: $surface;
        padding: 1 2; layout: vertical;
    }
    MCPInventoryScreen #mcp-inventory-scroll { height: 1fr; }
    MCPInventoryScreen #mcp-inventory-rows { height: 8; }
    MCPInventoryScreen #mcp-inventory-controls { height: auto; }
    MCPInventoryScreen #mcp-inventory-actions { height: auto; }
    """
    BINDINGS = [("escape", "dismiss", "Close inventory")]

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self.project_root = project_root
        self._read_task: asyncio.Task[None] | None = None
        self._generation = 0
        self._inventory: Inventory | None = None
        self._selected: Declaration | None = None

    def compose(self) -> ComposeResult:
        with containers.Vertical(id="mcp-inventory-panel"):
            with containers.VerticalScroll(id="mcp-inventory-scroll"):
                yield Static(
                    "Loading read-only Pi MCP package inventory…",
                    id="mcp-inventory-status",
                    markup=False,
                )
            yield OptionList(id="mcp-inventory-rows")
            with containers.Horizontal(id="mcp-inventory-actions"):
                for member in MCPDecision.members_with(MCPDecision):
                    yield MCPDecisionButton(member())
            with containers.Horizontal(id="mcp-inventory-controls"):
                yield Button("Refresh", id="refresh")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self.action_refresh()

    def on_unmount(self) -> None:
        self._generation += 1
        if self._read_task is not None:
            self._read_task.cancel()

    @on(Button.Pressed, "#refresh")
    def action_refresh(self) -> None:
        self._generation += 1
        if self._read_task is not None:
            self._read_task.cancel()
        self._inventory = None
        self._selected = None
        self.query_one("#mcp-inventory-rows", OptionList).clear_options()
        self._update_actions()
        self.query_one("#mcp-inventory-status", Static).update(
            "Loading read-only Pi MCP package inventory…"
        )
        self._read_task = asyncio.create_task(self._fetch(self._generation))

    async def _fetch(self, generation: int) -> None:
        try:
            inventory = await read_inventory(
                self.project_root
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # No partial data or error details from a configured executable.
            inventory = None
        if generation == self._generation and self.is_attached:
            self._inventory = inventory
            self.query_one("#mcp-inventory-status", Static).update(
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
                self.query_one("#mcp-inventory-rows", OptionList).add_options(options)

    def _selection(self) -> MCPSelection | None:
        if self._inventory is None or self._selected is None:
            return None
        return MCPSelection(self._inventory, self._selected)

    def _update_actions(self) -> None:
        selection = self._selection()
        for button in self.query(MCPDecisionButton):
            button.disabled = selection is None or not button.command.available(selection)

    @on(OptionList.OptionHighlighted, "#mcp-inventory-rows")
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

    @on(Button.Pressed, "#close")
    def close_inventory(self, event: Button.Pressed) -> None:
        self.dismiss()

    @on(Button.Pressed, "MCPDecisionButton")
    def open_decision(self, event: Button.Pressed) -> None:
        from toad.screens.mcp_decision import MCPDecisionScreen

        selection = self._selection()
        if selection is None or event.button.disabled:
            return
        command = cast(MCPDecisionButton, event.button).command
        self.app.push_screen(
            MCPDecisionScreen(selection, command),
            lambda _: self.action_refresh(),
        )
