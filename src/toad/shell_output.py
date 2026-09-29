"""Shell output owns its model independently of an optional mounted terminal."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from toad import ansi
from toad.widgets.shell_result import ShellResult

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation
    from toad.widgets.terminal import Terminal


class ShellOutput(ABC):
    @abstractmethod
    async def present(self, conversation: "Conversation") -> None: ...

    @abstractmethod
    def detach(self) -> None: ...


@dataclass
class ShellCommandOutput(ShellOutput):
    command: str

    async def present(self, conversation: "Conversation") -> None:
        await conversation.post(ShellResult(self.command))

    def detach(self) -> None:
        pass


class ShellTerminalOutput(ShellOutput):
    """The original ANSI state survives; a Terminal only projects that state."""

    def __init__(self, state: ansi.TerminalState) -> None:
        self.state = state
        self.finalized = False
        self.terminal: "Terminal | None" = None

    async def present(self, conversation: "Conversation") -> None:
        if self.terminal is not None:
            return
        terminal = await conversation.new_terminal()
        self.terminal = terminal
        terminal.set_state(self.state)
        terminal.update_size(terminal.width, terminal.height)
        terminal.set_write_to_stdin(self.state.write_stdin)
        terminal.project_state(None, None)
        if self.finalized:
            terminal.finalize()

    def project(self, scrollback: set[int] | None, alternate: set[int] | None) -> None:
        if self.terminal is not None:
            self.terminal.project_state(scrollback, alternate)
            if self.finalized:
                self.terminal.finalize()

    def finalize(self) -> None:
        self.finalized = True
        self.state.show_cursor = False
        self.project(None, None)

    def detach(self) -> None:
        self.terminal = None
