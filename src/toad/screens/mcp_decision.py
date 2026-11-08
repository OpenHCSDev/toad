"""The user's local PTY for package-owned Pi MCP decisions; no automatic answer."""

from __future__ import annotations

import asyncio

from textual import containers, events
from textual.app import ComposeResult
from textual.css.native import Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles
from ui_theme.scheme import AccentColour, WarningColour
from toad.widgets.acting_button import DismissButton
from toad.native_style import AutoHeight, FillHeight
from toad.screens.modal import CenteredScreen, DismissibleScreen, SurfacePanel
from toad.widget_actions import PriorityActions
from textual.widgets import Static

from toad.mcp_decision import LocalDecisionPTY
from toad.mcp_commands import MCPDecision, MCPSelection
from toad.widgets.terminal import ControlledTerminal
from textual import on


class DecisionPanel(SurfacePanel):
    native_theme = (NativeDeclaration.of(Styles.border, Keyword("round"), Variable(WarningColour.name)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = "90%"
        self.styles.height = "85%"
        self.styles.padding = (1, 2)


class DecisionStatus(Static):
    """What the package decision is doing, or how it ended."""


class DecisionTerminal(ControlledTerminal, FillHeight):
    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("round"), Variable(AccentColour.name)),
    )



class DecisionControls(AutoHeight, containers.Horizontal):
    """Its look is its bases."""


class MCPDecisionScreen(CenteredScreen, PriorityActions, DismissibleScreen[None]):

    def __init__(
        self,
        selection: MCPSelection,
        command: MCPDecision,
    ) -> None:
        super().__init__()
        self._selection, self._command = selection, command
        self._pty = LocalDecisionPTY(self._controller_visible)
        self._runner: asyncio.Task[None] | None = None
        self._running = False

    def compose(self) -> ComposeResult:
        with DecisionPanel():
            yield Static(
                "Only the installed Pi MCP package may make this decision. "
                "Inspect its complete display; type its challenge yourself. "
                "Toad never provides an answer. Cancel kills the child, but cannot "
                "undo a package decision already committed; refresh inventory.",
                markup=False,
            )
            yield DecisionStatus(
                "Rechecking the package inventory before launch…",
                markup=False,
            )
            yield DecisionTerminal()
            with DecisionControls():
                yield DismissButton("Cancel / close")

    @on(events.Mount)
    def on_mount(self) -> None:
        self._running = True
        terminal = self.query_one(DecisionTerminal)
        terminal.set_write_to_stdin(self._pty.write_user_input)
        terminal.focus()
        self._runner = asyncio.create_task(self._run_local_action())

    def _on_screen_suspend(self) -> None:
        super()._on_screen_suspend()
        self._stop()  # A covered modal is not a controlling local terminal.

    def _on_screen_resume(self, event: events.ScreenResume) -> None:
        super()._on_screen_resume(event)
        if self._runner is not None and not self._running:
            self.query_one(DecisionStatus).update(
                "Controller hidden; child stopped. A prior package write may have committed. Close and refresh."
            )

    def on_unmount(self) -> None:
        self._stop()

    def _stop(self) -> None:
        self._running = False
        # Visibility revokes the same acquired child. Acquisition registers its
        # exact handles even if visibility changes while spawn is pending;
        # the original resource scope always retires and reaps them.
        self._pty.stop()

    async def _run_local_action(self) -> None:
        terminal = self.query_one(DecisionTerminal)

        async def show(text: str) -> None:
            if text and self._controller_visible():
                await terminal.write(text)

        try:
            outcome = await self._pty.run(
                selection=self._selection,
                command=self._command,
                show=show,
                state=terminal.state,
            )
        except asyncio.CancelledError:
            self._pty.stop()
            raise
        finally:
            terminal.finalize()
        if self._controller_visible():
            self.query_one(DecisionStatus).update(outcome.message)

    def _controller_visible(self) -> bool:
        return self._running and self.is_attached and self.app.screen is self

    def dismiss_control(self) -> None:
        self._stop()
        super().dismiss_control()
