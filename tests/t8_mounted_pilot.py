"""No providers: real resume modal and PTY command using isolated durable state."""

import asyncio
import shlex
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Static

from toad.db import DB, Session, SessionMeta
from toad.screens.session_resume_modal import SessionResumeModal
from toad.widgets.command_pane import CommandPane
from toad.terminal_execution import Command, TerminalExecution


class MountedApp(App):
    def __init__(self, command):
        super().__init__()
        self.execution = TerminalExecution(command)

    def compose(self) -> ComposeResult:
        yield Static("T8 mounted local acceptance")
        yield CommandPane(self.execution)


async def main():
    with tempfile.TemporaryDirectory(prefix="t8-mounted-") as directory:
        root = Path(directory)
        with patch("toad.db.paths.get_state", return_value=root):
            db = DB()
            assert await db.create()
            pk = await db.session_new(
                "Saved T8",
                "Agent",
                "saved-agent",
                "saved-session",
                meta=SessionMeta(root, {"identity": "saved-agent"}),
            )
            output = root / "environment.txt"
            script = (
                "import os,pathlib; pathlib.Path("
                + repr(str(output))
                + ").write_text('|'.join(os.environ[k] for k in ('FORCE_COLOR','TTY_COMPATIBLE','TERM','COLORTERM','TOAD','CLICOLOR')))"
            )
            app = MountedApp(Command.for_script(shlex.join((sys.executable, "-c", script))))
            async with app.run_test(size=(100, 30)) as pilot:
                pane = app.query_one(CommandPane)
                await asyncio.wait_for(pane.execute(app.execution), 10)
                assert pane.return_code == 0
                assert output.read_text() == "1|1|xterm-256color|truecolor|1|1"
                resumed = []
                modal = SessionResumeModal()
                await app.push_screen(modal, resumed.append)
                await pilot.pause()
                assert modal.session_table.row_count == 1
                assert modal.session_table.get_row(str(pk))[:2] == ["Agent", "Saved T8"]
                await modal.dissmiss_with_session(str(pk))
                await pilot.pause()
                assert resumed[0].meta_json.cwd == root
                assert resumed[0].agent_session_id == "saved-session"
                print(
                    "PASS: mounted PTY environment, resume rows and typed selection",
                    flush=True,
                )
            original = Path.home() / ".local/state/toad/toad.db"
            if original.exists():
                # Read only, before/after comparison on a SQLite backup owned by
                # this fixture. No live root cleanup hooks or runtime processes.
                with (
                    sqlite3.connect(f"file:{original}?mode=ro", uri=True) as source,
                    sqlite3.connect(root / "copy.db") as copied,
                ):
                    source.backup(copied)
                    raw = copied.execute(
                        "SELECT * FROM sessions ORDER BY id"
                    ).fetchall()
                    typed = Session.read(
                        copied.execute("SELECT * FROM sessions ORDER BY id")
                    )
                    assert len(raw) == len(typed)
                    import json

                    for before, after in zip(raw, typed, strict=True):
                        assert before[:7] == (
                            after.id,
                            after.agent,
                            after.agent_identity,
                            after.agent_session_id,
                            after.title,
                            after.protocol,
                            after.prompt_count,
                        )
                        assert (
                            json.loads(before[9])["agent_data"]
                            == after.meta_json.agent_data
                        )
                        assert json.loads(before[9])["cwd"] == str(after.meta_json.cwd)
                    assert (
                        copied.execute("SELECT * FROM sessions ORDER BY id").fetchall()
                        == raw
                    )
                    print(
                        f"PASS: all {len(typed)} original saved session identities/agent definitions/directories preserved; copy unchanged",
                        flush=True,
                    )


if __name__ == "__main__":
    asyncio.run(main())
