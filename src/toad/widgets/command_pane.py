"""Catalog command projection borrows the original terminal operation."""
import os
from typing import ClassVar

from textual.css.native import DeclaresTheme, Keyword, NativeDeclaration, Percent, TextVariable, Variable
from textual.css.styles import Styles
from ui_theme.scheme import ErrorColour, PrimaryColour, SuccessColour

from toad.core.source_events import CommandComplete
from toad.core_event_carrier import CoreEventReceiver
from toad.terminal_environment import TerminalEnvironment
from toad.native_style import NoScrollbars
from toad.terminal_execution import Command, TerminalExecution
from toad.widgets.terminal import Terminal
from textual.events import Mount
from textual import on


class CommandFrame(DeclaresTheme):
    """The frame of a catalog command that has not finished."""

    native_theme: ClassVar[tuple[NativeDeclaration, ...]] = (
        NativeDeclaration.of(Styles.border, Keyword("tab"), Variable(PrimaryColour.name)),
    )


class SucceededCommandFrame(CommandFrame):
    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("tab"), TextVariable(SuccessColour.name), Percent(70)),
    )


class FailedCommandFrame(CommandFrame):
    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("tab"), TextVariable(ErrorColour.name), Percent(50)),
    )


class CommandPane(NoScrollbars, CoreEventReceiver, Terminal):
    native_theme = (NativeDeclaration.of(Styles.background, Keyword("black"), Percent(10)),)
    frame: type[CommandFrame] = CommandFrame

    def __init__(self, execution: TerminalExecution):
        self.execution = execution
        super().__init__()
        self.set_state(execution.state)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (1, 1)

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        return (*super().native_declarations(), *self.frame.declared_theme())

    @property
    def return_code(self) -> int | None:
        return self.execution.operation.outcome().return_code

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
            completion = await execution.operation.wait()
            self.project_state(None, None)
            if final:
                self.frame = (FailedCommandFrame, SucceededCommandFrame)[completion.successful]
                self.app.update_styles(self)
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
        def compose(self) -> ComposeResult:
            yield CommandPane(TerminalExecution(Command.for_script(COMMAND)))

        @on(Mount)
        def on_mount(self) -> None:
            command_pane = self.query_one(CommandPane)
            command_pane.border_title = Content(COMMAND)
            self.run_worker(command_pane.execute(command_pane.execution))

    app = CommandApp()
    app.run()
