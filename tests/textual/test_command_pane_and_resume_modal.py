from agent_comms.repo import Checkout
"""Textual-facing: the command pane (a widget running a terminal execution) gives its child the terminal environment, and the resume modal (a Textual screen) lists saved sessions and returns the chosen one typed."""

import asyncio
import shlex
import sys
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Static

from toad.agent_schema import AgentDefinition
from toad.db import DB, SessionMeta
from toad.screens.session_resume_modal import SessionResumeModal
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


async def test_the_resume_modal_lists_a_saved_session_and_returns_it_typed(tmp_path):
    with patch("toad.db.paths.get_state", return_value=tmp_path):
        db = DB()
        await db.create()
        saved = AgentDefinition.decode({"identity": "saved-agent", "name": "Agent", "run_command": {"*": "agent"}})
        pk = await db.session_new("Saved session", "Agent", "saved-agent", "saved-session",
                                  meta=SessionMeta(Checkout(tmp_path), saved))
        app = MountedApp(Command.for_script("true"))
        async with app.run_test(size=(100, 30)) as pilot:
            resumed = []
            modal = SessionResumeModal()
            await app.push_screen(modal, resumed.append)
            await pilot.pause()
            assert modal.session_table.row_count == 1
            assert modal.session_table.get_row(str(pk))[:2] == ["Agent", "Saved session"]
            await modal.dissmiss_with_session(str(pk))
            await pilot.pause()
            assert resumed[0].meta_json.cwd == tmp_path
            assert resumed[0].agent_session_id == "saved-session"
