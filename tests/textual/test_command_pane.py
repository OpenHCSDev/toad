"""Textual-facing: the command pane (a widget running a terminal execution) gives its child the terminal environment."""
import asyncio
import shlex
import sys

from textual.app import App, ComposeResult
from textual.widgets import Static

from toad.terminal_execution import Command, TerminalExecution
from toad.textual_colours import ThemedApp
from toad.widgets.command_pane import CommandPane


class MountedApp(ThemedApp, App):
    def __init__(self, command):
        super().__init__()
        self.execution = TerminalExecution(command)

    def compose(self) -> ComposeResult:
        yield Static("Mounted local acceptance")
        yield CommandPane(self.execution)


async def test_a_command_in_the_pane_sees_the_terminal_environment(tmp_path):
    output = tmp_path / "environment.txt"
    script = (
        "import os,pathlib; pathlib.Path(" + repr(str(output))
        + ").write_text('|'.join(os.environ[k] for k in ('FORCE_COLOR','TTY_COMPATIBLE','TERM','COLORTERM','TOAD','CLICOLOR')))"
    )
    app = MountedApp(Command.for_script(shlex.join((sys.executable, "-c", script))))
    async with app.run_test(size=(100, 30)):
        pane = app.query_one(CommandPane)
        await asyncio.wait_for(pane.execute(app.execution), 10)
        assert pane.return_code == 0
        assert output.read_text() == "1|1|xterm-256color|truecolor|1|1"
