"""Optional projection of the operational ACP terminal execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from textual.content import Content
from textual.message import Message

from agent_comms.mro_dispatch import MroDispatch, handles
from toad.terminal_execution import (
    TerminalExecution, TerminalCompletion, FailedTerminalOutcome,
    RunningTerminalOutcome, UnstartedTerminalOutcome, RetiredTerminalOutcome,
)
from toad.widgets.terminal import Terminal

if TYPE_CHECKING:
    from toad.agent_surface import AttachedSurfaceBinding
    from toad.acp.terminal_controller import TerminalController


class TerminalTool(Terminal, MroDispatch):
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
        outcome = self.execution.outcome
        handlers = tuple(self.handlers_for(outcome))
        if not handlers:
            raise TypeError(f"No native terminal view for {type(outcome).__name__}")
        self.consume_handlers_sync(outcome, handlers)

    @handles(RunningTerminalOutcome, UnstartedTerminalOutcome, RetiredTerminalOutcome)
    def present_pending(self, outcome) -> None:
        """These original outcomes have no completion border to draw."""

    @handles(TerminalCompletion)
    def present_completion(self, outcome) -> None:
        self.finalize()
        self.set_class(outcome.successful, "-success")
        self.set_class(not outcome.successful, "-error")
        if not outcome.successful:
            self.border_title = Content(f"{self.execution.command} [{outcome.label}]")

    @handles(FailedTerminalOutcome)
    def present_failure(self, outcome) -> None:
        self.finalize()
        self.set_class(True, "-error")
        self.border_title = Content(f"{self.execution.command} [{outcome.error}]")
