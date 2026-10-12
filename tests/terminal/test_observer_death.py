"""Killing the comms observer of a running Toad ends the app: one saved failure naming the observer, exit status 1, the terminal restored and no process left behind."""

from pathlib import Path
import signal
import sys

from support.terminal import terminal_running

APP = Path(__file__).parents[1] / "support" / "observed_app.py"
LEAVE_ALTERNATE_SCREEN = "\x1b[?1049l"


async def test_a_killed_observer_ends_the_app_with_one_saved_failure(workspace, terminal_emulator):
    import psutil

    workspace.comms.messaging.initialize_private_initial_protocol()
    logs = workspace.roots.attempt / "state" / "toad" / "logs"
    noted = workspace.project / "observer-pid"
    async with terminal_running(workspace, terminal_emulator, (sys.executable, str(APP), str(workspace.project)),
                                size=(43, 140)) as terminal:
        await terminal.until(noted.exists, seconds=60, why="the observer to answer the sidebar")
        await terminal.until_shows("New Session", seconds=30)
        app = psutil.Process(terminal.process.pid)
        observer = psutil.Process(int(noted.read_text()))
        assert observer.ppid() == app.pid, (observer.ppid(), app.pid)
        started = app.children(recursive=True)
        shown = len(terminal.output)
        observer.send_signal(signal.SIGKILL)
        status = await terminal.until_exit(seconds=20)
        tape = terminal.output[shown:].decode(errors="replace")
        _, alive = psutil.wait_procs(started, timeout=5)
    saved = [path.read_text() for path in logs.glob("Terminal_crash*.txt")]
    assert status == 1, (status, tape[-2000:])
    assert len(saved) == 1, saved
    assert "ObserverDied" in saved[0], saved[0]
    assert f"The comms observer (pid {observer.pid}) was killed by signal 9" in saved[0], saved[0]
    assert "BrokenPipeError" not in saved[0] and "BrokenPipeError" not in tape
    assert LEAVE_ALTERNATE_SCREEN in tape, tape[-2000:]
    assert not alive, [(process.pid, process.cmdline()) for process in alive]
