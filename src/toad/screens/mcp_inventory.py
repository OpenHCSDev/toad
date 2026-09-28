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
from toad.mcp_inventory import (
    Declaration,
    Inventory,
    read_inventory,
    render_inventory,
)


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
                yield Button("Approve project", id="trust_approve", disabled=True)
                yield Button("Deny project", id="trust_deny", disabled=True)
                yield Button("Require call asks", id="calls_ask", disabled=True)
                yield Button("Allow autonomous calls", id="calls_allow", disabled=True)
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
            project = eligible and row.scope.allows_trust_decision()
            calls = eligible and row.status.allows_call_decision()
        for identifier, enabled in (
            ("trust_approve", project),
            ("trust_deny", project),
            ("calls_allow", calls),
            ("calls_ask", calls),
        ):
            self.query_one(f"#{identifier}", Button).disabled = not enabled

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

    @on(Button.Pressed, "#close")
    def close_inventory(self, event: Button.Pressed) -> None:
        self.dismiss()

    @on(Button.Pressed, "#trust_approve")
    def approve_project(self, event: Button.Pressed) -> None:
        self.open_decision(event, "trust", "approve")

    @on(Button.Pressed, "#trust_deny")
    def deny_project(self, event: Button.Pressed) -> None:
        self.open_decision(event, "trust", "deny")

    @on(Button.Pressed, "#calls_allow")
    def allow_calls(self, event: Button.Pressed) -> None:
        self.open_decision(event, "calls", "allow")

    @on(Button.Pressed, "#calls_ask")
    def ask_calls(self, event: Button.Pressed) -> None:
        self.open_decision(event, "calls", "ask")

    def open_decision(self, event: Button.Pressed, action: DecisionAction, decision: Decision) -> None:
        from toad.screens.mcp_decision import MCPDecisionScreen

        snapshot, row = self._inventory, self._selected
        if snapshot is None or row is None or event.button.disabled:
            return
        self.app.push_screen(
            MCPDecisionScreen(snapshot, row, action=action, decision=decision),
            lambda _: self.action_refresh(),
        )
