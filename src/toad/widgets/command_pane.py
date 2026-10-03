"""Catalog command projection borrows the original terminal operation."""
import os

from toad.core.source_events import CommandComplete
from toad.core_event_carrier import CoreEventReceiver
from toad.terminal_environment import TerminalEnvironment
from toad.terminal_execution import Command, TerminalExecution
from toad.widgets.terminal import Terminal


class CommandPane(CoreEventReceiver, Terminal):
    DEFAULT_CSS = """
    CommandPane {
        scrollbar-size: 0 0;
    }
    """

    def __init__(self, execution: TerminalExecution, *, name=None, id=None, classes=None):
        self.execution = execution
        super().__init__(name=name, id=id, classes=classes)
        self.set_state(execution.state)

    @property
    def return_code(self) -> int | None:
        return self.execution.outcome.return_code

    @property
    def is_cooked(self) -> bool:
        return self.execution.is_cooked

    def resize_process(self, width: int, height: int) -> None:
        self.execution.update_size(width, height)

    def present_execution(self, scrollback, alternate) -> None:
        self.project_state(scrollback, alternate)

    async def execute(self, execution: TerminalExecution, *, final: bool = True) -> None:
        self.execution.detach(self)
        self.execution = execution
        execution.attach(self)
        self.anchor()
        try:
            await self.wait_for_refresh()
            self.update_size(*self.scrollable_content_region.size)
            await execution.start()
            completion = await execution.wait_for_exit()
            self.project_state(None, None)
            if final:
                self.set_class(completion.successful, "-success")
                self.set_class(not completion.successful, "-fail")
                self.publish_core(CommandComplete(completion.return_code))
        finally:
            # The native worker may be cancelled before async Unmount runs.
            # Joining the original operation also covers cancelled acquisition.
            await execution.close()

    async def cancel_command(self) -> None:
        await self.execution.close()

    async def on_unmount(self) -> None:
        await self.cancel_command()


if __name__ == "__main__":
    from textual.app import App, ComposeResult
    from textual.content import Content

    COMMAND = TerminalEnvironment.login_shell(os.environ)
    # COMMAND = "python test_input.py"

    # COMMAND = "htop"
    # COMMAND = "python test_scroll_margins.py"

    # COMMAND = "python cpr.py"

    COMMAND = "python test_input.py"

    class CommandApp(App):
        CSS = """
        Screen {
            align: center middle;
        }
        CommandPane {
            # background: blue 20%;
            scrollbar-gutter: stable;
            background: black 10%;
            max-height: 40;
            # border: green;
            border: tab $text-primary;            
            margin: 0 2;
        }
        # CommandPane {
        #     width: 1fr;
        #     height: 1fr;
        #     # background: black 10%;
        #     # color: white;
        #     background: ansi_default;
        #     # color: ansi_default;
        # }
        """

        def compose(self) -> ComposeResult:
            yield CommandPane(TerminalExecution(Command.for_script(COMMAND)))

        def on_mount(self) -> None:
            command_pane = self.query_one(CommandPane)
            command_pane.border_title = Content(COMMAND)
            self.run_worker(command_pane.execute(command_pane.execution))

    app = CommandApp()
    app.run()
