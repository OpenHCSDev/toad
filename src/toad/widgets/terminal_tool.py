"""Optional projection of the operational ACP terminal execution."""
from textual.content import Content

from toad.terminal_execution import TerminalExecution
from toad.widgets.terminal import Terminal


class TerminalTool(Terminal):
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
        if (return_code := self.execution.return_code) is not None:
            self.finalize()
            self.set_class(return_code == 0, "-success")
            self.set_class(return_code != 0, "-error")
            if return_code:
                self.border_title = Content(f"{self.execution.command} [{return_code}]")
