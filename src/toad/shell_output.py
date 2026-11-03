"""Shell output owns its model independently of an optional mounted terminal."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from toad import ansi


class ShellOutput(ABC):
    @abstractmethod
    def detach(self) -> None: ...


@dataclass
class ShellCommandOutput(ShellOutput):
    command: str

    def detach(self) -> None:
        pass


class CurrentShellOutput(ABC):
    """Whether the shell has a current ANSI model, not whether a view is mounted."""

    def for_line(self, create: Callable[[], ShellTerminalOutput]) -> ShellTerminalOutput:
        return create()

    def format_input(self, text: str, paste: bool) -> str:
        return text

    def focus(self) -> None:
        """An absent output has no projected terminal to focus."""

    def finalize(self) -> None:
        """An absent output has no ANSI model to finalize."""

    def update_size(self, width: int, height: int) -> None:
        """An absent output has no model geometry to change."""


@dataclass(frozen=True)
class NoCurrentShellOutput(CurrentShellOutput):
    """No current model exists before output, after a command or after retirement."""


class ShellTerminalOutput(ShellOutput, CurrentShellOutput):
    """The original ANSI state survives; a Terminal only projects that state."""

    def __init__(self, state: ansi.TerminalState) -> None:
        self.state = state
        self.finalized = False
        self.terminal = None

    def for_line(self, create: Callable[[], ShellTerminalOutput]) -> ShellTerminalOutput:
        return create() if self.finalized else self

    def format_input(self, text: str, paste: bool) -> str:
        if paste and self.state.bracketed_paste:
            return f"\x1b[200~{text}\x1b[201~"
        return text

    def update_size(self, width: int, height: int) -> None:
        self.state.update_size(width, height)

    def attach(self, terminal) -> None:
        """Borrow a native terminal; the output retains its original model."""
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

    def focus(self) -> None:
        if self.terminal is not None:
            self.terminal.focus(scroll_visible=False)

    def finalize(self) -> None:
        self.finalized = True
        self.state.show_cursor = False
        self.project(None, None)

    def detach(self) -> None:
        self.terminal = None
