"""A UI exception in a real terminal leaves the error printed, exits with status 1 and saves one owner-only traceback file without local variables."""

from pathlib import Path
import sys

from support.terminal import terminal_running

APP = Path(__file__).parents[1] / "support" / "terminal_crash_app.py"


async def test_a_ui_exception_prints_the_error_and_saves_one_private_traceback(workspace, terminal_emulator):
    workspace.comms.messaging.initialize_private_initial_protocol()
    logs = workspace.roots.attempt / "state" / "toad" / "logs"
    async with terminal_running(workspace, terminal_emulator, (sys.executable, str(APP), str(workspace.project)),
                                size=(43, 140)) as terminal:
        status = await terminal.until_exit(seconds=30)
        tape = terminal.output.decode(errors="replace")
    files = list(logs.glob("Terminal_crash*.txt"))
    assert status == 1, (status, tape[-2000:])
    assert len(files) == 1, files
    body = files[0].read_text()
    assert "RecursionError: CONTROLLED_TERMINAL_CAPTURE_PROOF" in body
    assert "fail_after_paint" in body and "Traceback" in body
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert "Terminal traceback saved:" in tape
    assert "CONTROLLED_TERMINAL_CAPTURE_PROOF" in tape
    assert "locals" not in body
