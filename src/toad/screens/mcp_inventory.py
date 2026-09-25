"""Optional read-only view of the versioned Pi-package MCP inventory."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from textual import containers, on
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from toad.mcp_decision import Decision, DecisionAction
from toad.mcp_inventory import Declaration, Inventory, read_inventory, render_inventory


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

    def __init__(self, project_root: Path, *, node_path: str, cli_path: str) -> None:
        super().__init__()
        self.project_root = project_root
        self.node_path = node_path
        self.cli_path = cli_path
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
                yield Button(
                    "Approve project (held)", id="trust_approve", disabled=True
                )
                yield Button("Deny project", id="trust_deny", disabled=True)
                yield Button("Require call asks", id="calls_ask", disabled=True)
                yield Button(
                    "Allow autonomous calls (held)", id="calls_allow", disabled=True
                )
            with containers.Horizontal(id="mcp-inventory-controls"):
                yield Button("Refresh", id="refresh")
                yield Button("Close", id="close")

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
        self.query_one("#mcp-inventory-rows", OptionList).clear_options()
        self._update_actions()
        self.query_one("#mcp-inventory-status", Static).update(
            "Loading read-only Pi MCP package inventory…"
        )
        self._read_task = asyncio.create_task(self._fetch(self._generation))

    async def _fetch(self, generation: int) -> None:
        try:
            inventory = await read_inventory(
                self.project_root, node_path=self.node_path, cli_path=self.cli_path
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
                        f"{row.scope} / {row.id} · {row.status}",
                        id=f"{row.scope}:{row.id}",
                    )
                    for row in (*inventory.user, *inventory.project)
                ]
                self.query_one("#mcp-inventory-rows", OptionList).add_options(options)

    def _update_actions(self) -> None:
        row, snapshot = self._selected, self._inventory
        if row is None or snapshot is None or os.name != "posix":
            project = calls = False
        else:
            eligible = row.effective and row.enabled and snapshot.project_trusted_saved
            project = eligible and row.scope == "project"
            calls = eligible and row.status == "approved"
        for identifier, enabled in (("trust_deny", project), ("calls_ask", calls)):
            self.query_one(f"#{identifier}", Button).disabled = not enabled
        # Positive grants held pending independent correction of package
        # deny/reapprove grant revival; only revocations can launch here.
        self.query_one("#trust_approve", Button).disabled = True
        self.query_one("#calls_allow", Button).disabled = True

    @on(OptionList.OptionHighlighted, "#mcp-inventory-rows")
    def on_row_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        snapshot = self._inventory
        self._selected = (
            next(
                (
                    row
                    for row in (*snapshot.user, *snapshot.project)
                    if f"{row.scope}:{row.id}" == event.option_id
                ),
                None,
            )
            if snapshot is not None
            else None
        )
        self._update_actions()

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        identifier = event.button.id
        if identifier == "close":
            self.dismiss()
        elif identifier == "refresh":
            self.action_refresh()
        elif identifier in {"trust_deny", "calls_ask"}:
            from toad.screens.mcp_decision import MCPDecisionScreen

            snapshot, row = self._inventory, self._selected
            if snapshot is None or row is None or event.button.disabled:
                return
            action: DecisionAction = "trust" if identifier == "trust_deny" else "calls"
            decision: Decision = "deny" if identifier == "trust_deny" else "ask"
            self.app.push_screen(
                MCPDecisionScreen(
                    snapshot,
                    row,
                    action=action,
                    decision=decision,
                    node_path=self.node_path,
                    cli_path=self.cli_path,
                ),
                lambda _: self.action_refresh(),
            )
