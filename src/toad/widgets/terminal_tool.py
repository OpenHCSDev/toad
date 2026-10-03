"""Optional projection of the operational ACP terminal execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from textual.content import Content
from textual.message import Message

from toad.terminal_execution import TerminalExecution
from toad.widgets.terminal import Terminal

if TYPE_CHECKING:
    from toad.acp.agent_controller import AttachedSurfaceBinding
    from toad.acp.terminal_controller import TerminalController


class TerminalTool(Terminal):
    @dataclass
    class Projection(Message):
        """A native render request borrows its original acquired resources."""

        binding: AttachedSurfaceBinding
        controller: TerminalController
        terminal_id: str
        execution: TerminalExecution

    DEFAULT_CSS = """
    TerminalTool {
        height: auto;
        border: panel $text-primary;
    }
    """

    def __init__(self, execution: TerminalExecution, *, id: str) -> None:
        self.execution = execution
        super().__init__(id=id, size=(execution.state.width, execution.state.height))
        self.border_title = Content(str(execution.command))

    def on_mount(self) -> None:
        super().on_mount()
        self.execution.attach(self)

    def on_unmount(self) -> None:
        self.execution.detach(self)

    def resize_process(self, width: int, height: int) -> None:
        self.execution.update_size(width, height)

    def present_execution(self) -> None:
        self.project_state(None, None)
        self.execution.outcome.present(self, self.execution.command)
