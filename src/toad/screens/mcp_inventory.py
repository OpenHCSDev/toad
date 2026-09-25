"""Optional read-only view of the versioned Pi-package MCP inventory."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual import containers, on
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from toad.mcp_inventory import read_inventory, render_inventory


class MCPInventoryScreen(ModalScreen[None]):
    """The Pi package owns the inventory; this screen never owns decisions."""

    DEFAULT_CSS = """
    MCPInventoryScreen { align: center middle; }
    MCPInventoryScreen #mcp-inventory-panel {
        width: 85%; height: 85%; border: round $accent; background: $surface;
        padding: 1 2; layout: vertical;
    }
    MCPInventoryScreen #mcp-inventory-scroll { height: 1fr; }
    MCPInventoryScreen #mcp-inventory-controls { height: auto; }
    """
    BINDINGS = [("escape", "dismiss", "Close inventory")]

    def __init__(self, project_root: Path, *, node_path: str, cli_path: str) -> None:
        super().__init__()
        self.project_root = project_root
        self.node_path = node_path
        self.cli_path = cli_path
        self._read_task: asyncio.Task[None] | None = None
        self._generation = 0

    def compose(self) -> ComposeResult:
        with containers.Vertical(id="mcp-inventory-panel"):
            with containers.VerticalScroll(id="mcp-inventory-scroll"):
                yield Static(
                    "Loading read-only Pi MCP package inventory…",
                    id="mcp-inventory-status",
                    markup=False,
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
            self.query_one("#mcp-inventory-status", Static).update(
                render_inventory(inventory)
            )

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss()
        elif event.button.id == "refresh":
            self.action_refresh()
