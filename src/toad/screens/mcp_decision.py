"""The user's local PTY for package-owned Pi MCP decisions; no automatic answer."""

from __future__ import annotations

import asyncio

from textual import containers, events, on
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from toad.mcp_decision import Decision, DecisionAction, LocalDecisionPTY
from toad.mcp_inventory import Declaration, Inventory
from toad.widgets.terminal import Terminal


class MCPDecisionScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    MCPDecisionScreen { align: center middle; }
    MCPDecisionScreen #mcp-decision-panel {
        width: 90%; height: 85%; border: round $warning; background: $surface;
        padding: 1 2; layout: vertical;
    }
    MCPDecisionScreen #mcp-decision-terminal { height: 1fr; border: round $accent; }
    MCPDecisionScreen #mcp-decision-controls { height: auto; }
    """
    BINDINGS = [("escape", "close_decision", "Cancel local action")]

    def __init__(
        self,
        inventory: Inventory,
        row: Declaration,
        *,
        action: DecisionAction,
        decision: Decision,
        node_path: str,
        cli_path: str,
    ) -> None:
        super().__init__()
        self._inventory, self._row = inventory, row
        self._action, self._decision = action, decision
        self._node_path, self._cli_path = node_path, cli_path
        self._pty = LocalDecisionPTY()
        self._runner: asyncio.Task[None] | None = None
        self._running = False

    def compose(self) -> ComposeResult:
        with containers.Vertical(id="mcp-decision-panel"):
            yield Static(
                "Only the installed Pi MCP package may make this decision. "
                "Inspect its complete display; type its challenge yourself. "
                "Toad never provides an answer. Cancel closes the child.",
                markup=False,
            )
            yield Static(
                "Rechecking the package inventory before launch…",
                id="mcp-decision-status",
                markup=False,
            )
            yield Terminal(id="mcp-decision-terminal")
            with containers.Horizontal(id="mcp-decision-controls"):
                yield Button("Cancel / close", id="cancel")

    def on_mount(self) -> None:
        self._running = True
        terminal = self.query_one("#mcp-decision-terminal", Terminal)
        terminal.set_write_to_stdin(self._pty.write_user_input)
        terminal.focus()
        self._runner = asyncio.create_task(self._run_local_action())

    def _on_screen_suspend(self) -> None:
        super()._on_screen_suspend()
        self._stop()  # A covered modal is not a controlling local terminal.

    def _on_screen_resume(self, event: events.ScreenResume) -> None:
        super()._on_screen_resume(event)
        if self._runner is not None and not self._running:
            self.query_one("#mcp-decision-status", Static).update(
                "Controller was hidden; local action cancelled. Close and refresh the inventory."
            )

    def on_unmount(self) -> None:
        self._stop()

    def _stop(self) -> None:
        self._running = False
        # Do not cancel create_subprocess_exec mid-spawn: the process may exist
        # before the coroutine returns its handle. The bounded runner checks
        # visibility after spawn and always reaps a child in its finally block.
        self._pty.stop()

    async def _run_local_action(self) -> None:
        terminal = self.query_one("#mcp-decision-terminal", Terminal)

        async def show(text: str) -> None:
            if text and self._controller_visible():
                await terminal.write(text)

        try:
            outcome = await self._pty.run(
                inventory=self._inventory,
                row=self._row,
                action=self._action,
                decision=self._decision,
                node_path=self._node_path,
                cli_path=self._cli_path,
                show=show,
                controller_visible=self._controller_visible,
            )
        except asyncio.CancelledError:
            self._pty.stop()
            raise
        finally:
            terminal.finalize()
        if self._controller_visible():
            messages = {
                "exited_zero": "CLI exited successfully. Check its visible receipt; any decision applies on the next Pi turn.",
                "exited_error": "Package CLI failed; no Toad approval is asserted.",
                "stale_snapshot": "Inventory changed or became unavailable. Action refused before launch; refresh it.",
                "output_limit": "Too much CLI output; action cancelled without Toad approval.",
                "timeout": "Local decision timed out; action cancelled without Toad approval.",
                "unsupported": "This action is unsupported or on safety hold.",
                "unavailable": "Local PTY/package unavailable. No action launched.",
                "controller_lost": "Controller disappeared; action cancelled.",
            }
            self.query_one("#mcp-decision-status", Static).update(
                messages.get(outcome, "Action unavailable.")
            )

    def _controller_visible(self) -> bool:
        return self._running and self.is_attached and self.app.screen is self

    def action_close_decision(self) -> None:
        self._stop()
        self.dismiss()

    @on(Button.Pressed, "#cancel")
    def on_cancel(self) -> None:
        self.action_close_decision()
