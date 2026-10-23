"""A mounted UI exception is shown while the actual terminal remains usable."""

from pathlib import Path
import sys

from support.terminal import terminal_running

APP = Path(__file__).parents[1] / "support" / "terminal_crash_app.py"


async def test_a_ui_exception_is_shown_and_the_terminal_can_keep_working(workspace, terminal_emulator):
    async with terminal_running(workspace, terminal_emulator, (sys.executable, str(APP), str(workspace.project), str(workspace.roots.wire)),
                                size=(43, 140)) as terminal:
        await terminal.until_shows("CONTROLLED_TERMINAL_CAPTURE_PROOF")
        assert terminal.returncode is None
        await terminal.until_shows("#comms")
        await terminal.click_text("#comms")
        await terminal.until_shows("❯")
        await terminal.send("RECOVERED_DRAFT")
        await terminal.until_shows("RECOVERED_DRAFT")
        await terminal.send("\x11")
        status = await terminal.until_exit(seconds=20)
        tape = terminal.output.decode(errors="replace")
    assert status == 0, (status, tape[-2000:])
    assert "CONTROLLED_TERMINAL_CAPTURE_PROOF" in tape
