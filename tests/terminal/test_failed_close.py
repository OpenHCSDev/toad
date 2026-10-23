"""Quitting Toad when a step of closing raises still ends the process: the failure is saved and announced, the exit status is 1 and no process is left behind."""

from pathlib import Path
import sys

from support.terminal import terminal_running

APP = Path(__file__).parents[1] / "support" / "failed_close_app.py"


async def test_a_close_step_that_raises_still_ends_the_process_and_saves_the_failure(workspace, terminal_emulator):
    import psutil

    logs = workspace.roots.attempt / "state" / "toad" / "logs"
    async with terminal_running(workspace, terminal_emulator, (sys.executable, str(APP), str(workspace.project), str(workspace.roots.wire)),
                                size=(43, 140)) as terminal:
        await terminal.until_shows("#comms")
        await terminal.click_text("#comms")
        await terminal.until((workspace.project / "conversation-open").exists, seconds=60,
                             why="a conversation to open")
        started = psutil.Process(terminal.process.pid).children(recursive=True)
        assert any("spawn_main" in " ".join(process.cmdline()) for process in started), started
        await terminal.send("\x11")  # ctrl+q
        status = await terminal.until_exit(seconds=20)
        tape = terminal.output.decode(errors="replace")
        _, alive = psutil.wait_procs(started, timeout=5)
    saved = [path.read_text() for path in logs.glob("Terminal_crash*.txt")]
    assert status == 1, (status, tape[-2000:])
    assert any("CloseStepFailed: goal controls" in text for text in saved), saved
    assert "Terminal traceback saved:" in tape, tape[-2000:]
    assert not alive, [(process.pid, process.cmdline()) for process in alive]
