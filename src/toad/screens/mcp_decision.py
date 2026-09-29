"""The user's local PTY for package-owned Pi MCP decisions; no automatic answer."""

from __future__ import annotations

import asyncio

from textual import containers, events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from toad.mcp_decision import LocalDecisionPTY
from toad.mcp_commands import MCPDecision, MCPSelection
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
    BINDINGS = [Binding("escape", "close_decision", "Cancel local action", priority=True)]

    def __init__(
        self,
        selection: MCPSelection,
        command: MCPDecision,
    ) -> None:
        super().__init__()
        self._selection, self._command = selection, command
        self._pty = LocalDecisionPTY()
        self._runner: asyncio.Task[None] | None = None
        self._running = False

    def compose(self) -> ComposeResult:
        with containers.Vertical(id="mcp-decision-panel"):
            yield Static(
                "Only the installed Pi MCP package may make this decision. "
                "Inspect its complete display; type its challenge yourself. "
                "Toad never provides an answer. Cancel kills the child, but cannot "
                "undo a package decision already committed; refresh inventory.",
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
                "Controller hidden; child stopped. A prior package write may have committed. Close and refresh."
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
                selection=self._selection,
                command=self._command,
                show=show,
                controller_visible=self._controller_visible,
            )
        except asyncio.CancelledError:
            self._pty.stop()
            raise
        finally:
            terminal.finalize()
        if self._controller_visible():
            self.query_one("#mcp-decision-status", Static).update(outcome.message)

    def _controller_visible(self) -> bool:
        return self._running and self.is_attached and self.app.screen is self

    def action_close_decision(self) -> None:
        self._stop()
        self.dismiss()

    @on(Button.Pressed, "#cancel")
    def on_cancel(self) -> None:
        self.action_close_decision()
