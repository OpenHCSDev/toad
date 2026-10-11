"""Directory watchers a test runs against a real native observer process."""

from __future__ import annotations

from multiprocessing import get_context
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

from textual.widget import Widget

from toad.core_event_carrier import CoreEventReceiver
from toad.directory_watcher import DirectoryWatcher, _observe_path


def blocked_observe_path(path, owner):
    """The observer process for a directory named ``blocked`` never finishes its recursive start."""
    if path.name != "blocked":
        return _observe_path(path, owner)

    def blocked_walk(*args, **kwargs):
        (path / "entered-recursive-walk").touch()
        threading.Event().wait()
        yield

    # The exact synchronous native startup boundary seen in a crash log.
    # Observer, child process, pipe and cancellation are real.
    with patch("watchdog.observers.inotify_c.os.walk", blocked_walk):
        _observe_path(path, owner)


class RecordingWidget(CoreEventReceiver, Widget):
    pass


class RecordingWatcher(DirectoryWatcher):
    """A real watcher that records that it was told of a change."""

    def __init__(self, path):
        super().__init__(path, RecordingWidget())
        self.received = threading.Event()

    def on_any_event(self, event):
        self.received.set()


def until(predicate, why: str = "watcher condition", seconds: float = 8) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, f"{why} not reached in {seconds}s"
        time.sleep(.01)


def stop(watcher) -> float:
    """Stop a watcher, check it finished cancelling, and return how long that took."""
    started = time.monotonic()
    watcher.stop()
    watcher.join(timeout=3)
    assert not watcher.is_alive(), "Watcher did not complete cancellation"
    assert not watcher.enabled
    return time.monotonic() - started


def abandon_parent(path: Path) -> None:
    """Start a watcher whose observer blocks, record the child's pid, and die without cleaning up."""
    with patch("toad.directory_watcher._observe_path", blocked_observe_path):
        watcher = RecordingWatcher(path)
        watcher.start()
        until(lambda: (path / "entered-recursive-walk").exists(), "the blocked recursive walk")
        (path / "child-pid").write_text(str(watcher._observation.process.pid))
        os._exit(0)


def close_pipe_with_unread_events(root: Path) -> None:
    """Close the owner's end of the pipe while native events are queued; the observer must exit 0."""
    context = get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_observe_path, args=(root, child))
    process.start()
    child.close()
    try:
        assert parent.poll(5), "Observer never became ready"
        parent.recv()
        for index in range(512):
            (root / str(index)).touch()
        assert parent.poll(5), "Native burst produced no unread pipe data"
        parent.close()  # Closing with unread events can send RESET, not EOF.
        process.join(3)
        assert process.exitcode == 0, f"Owner loss failed to cancel child: {process.exitcode}"
    finally:
        parent.close()
        if process.is_alive():
            process.kill()
            process.join(3)
        process.close()


if __name__ == "__main__":
    # Run as a script, so a test can read its exit code and stderr:
    #   watchers.py --abandon DIRECTORY    the parent that dies mid-start
    #   watchers.py --peer-close DIRECTORY the owner that closes its pipe
    {"--abandon": abandon_parent, "--peer-close": close_pipe_with_unread_events}[sys.argv[1]](Path(sys.argv[2]))
