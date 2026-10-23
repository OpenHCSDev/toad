"""A killed observer is reported while Toad stays usable and can quit cleanly."""

from pathlib import Path
import signal
import sys

from support.terminal import terminal_running

APP = Path(__file__).parents[1] / "support" / "observed_app.py"
LEAVE_ALTERNATE_SCREEN = "\x1b[?1049l"


async def test_a_killed_observer_is_reported_without_ending_the_app(workspace, terminal_emulator):
    import psutil

    noted = workspace.project / "observer-pid"
    async with terminal_running(workspace, terminal_emulator, (sys.executable, str(APP), str(workspace.project), str(workspace.roots.wire)),
                                size=(43, 140)) as terminal:
        await terminal.until(noted.exists, seconds=60, why="the observer to answer the sidebar")
        await terminal.until_shows("New Session", seconds=30)
        app = psutil.Process(terminal.process.pid)
        observer = psutil.Process(int(noted.read_text()))
        assert observer.ppid() == app.pid, (observer.ppid(), app.pid)
        started = app.children(recursive=True)
        shown = len(terminal.output)
        observer.send_signal(signal.SIGKILL)
        await terminal.until(lambda: terminal.shows("was killed by signal") or terminal.shows("ObserverDied"),
                             seconds=20, why="the observer's actual failure")
        assert terminal.returncode is None
        await terminal.send("\x11")
        status = await terminal.until_exit(seconds=20)
        tape = terminal.output[shown:].decode(errors="replace")
        _, alive = psutil.wait_procs(started, timeout=5)
    assert status == 0, (status, tape[-2000:])
    assert "BrokenPipeError" not in tape
    assert LEAVE_ALTERNATE_SCREEN in tape, tape[-2000:]
    assert not alive, [(process.pid, process.cmdline()) for process in alive]
