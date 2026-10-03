"""Real recursive inotify startup cancels; one surviving subscriber still receives events."""

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import psutil
from textual.widget import Widget
from toad.core_event_carrier import CoreEventReceiver

from toad.directory_watcher import DirectoryWatcher, _observe_path, _shared_observer_manager


def blocked_observe_path(path, owner):
    if path.name != "blocked":
        return _observe_path(path, owner)

    def blocked_walk(*args, **kwargs):
        (path / "entered-recursive-walk").touch()
        threading.Event().wait()
        yield

    # Hold the exact synchronous native startup boundary seen in the crash log.
    # Observer/child process/IPC/cancellation are real; no mocked completion.
    with patch("watchdog.observers.inotify_c.os.walk", blocked_walk):
        _observe_path(path, owner)


class RecordingWidget(CoreEventReceiver, Widget):
    pass


class RecordingWatcher(DirectoryWatcher):
    def __init__(self, path):
        super().__init__(path, RecordingWidget())
        self.received = threading.Event()

    def on_any_event(self, event):
        self.received.set()


def until(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "Watcher condition timed out"
        time.sleep(.01)


def stop(watcher):
    started = time.monotonic()
    watcher.stop()
    watcher.join(timeout=3)
    assert not watcher.is_alive(), "Watcher did not complete cancellation"
    assert not watcher.enabled
    return time.monotonic() - started


def abandon_parent(path):
    with patch("toad.directory_watcher._observe_path", blocked_observe_path):
        watcher = RecordingWatcher(path)
        watcher.start()
        until(lambda: (path / "entered-recursive-walk").exists())
        (path / "child-pid").write_text(str(watcher._observation.process.pid))
        os._exit(0)


def main():
    with tempfile.TemporaryDirectory(prefix="watcher-cancel-") as directory:
        root = Path(directory)
        blocked, healthy = root / "blocked", root / "healthy"
        blocked.mkdir()
        healthy.mkdir()
        watchers = []
        try:
            with patch("toad.directory_watcher._observe_path", blocked_observe_path):
                waiting = RecordingWatcher(blocked)
                watchers.append(waiting)
                waiting.start()
                until(lambda: (blocked / "entered-recursive-walk").exists())
                assert not waiting.enabled
                pid = waiting._observation.process.pid
                first, second = RecordingWatcher(healthy), RecordingWatcher(healthy)
                watchers.extend((first, second))
                first.start()
                second.start()
                until(lambda: first.enabled and second.enabled)
                assert first._observation is second._observation
                healthy_pid = first._observation.process.pid
                (healthy / "first").touch()
                assert first.received.wait(3) and second.received.wait(3)
                duration = stop(waiting)
                assert not psutil.pid_exists(pid), "Cancelled startup left a child"
                stop(first)
                assert second.enabled and psutil.pid_exists(healthy_pid)
                second.received.clear()
                (healthy / "second").touch()
                assert second.received.wait(3)
                rss = psutil.Process(healthy_pid).memory_info().rss
                stop(second)
                assert not psutil.pid_exists(healthy_pid)
                assert not _shared_observer_manager._observers
                print({"blocked_recursive_start_cancel_seconds": duration,
                       "shared_observer_rss_bytes": rss,
                       "independent_directory_and_surviving_subscriber": "pass"})
            early = RecordingWatcher(healthy)
            watchers.append(early)
            early.stop()
            early.start()
            early.join(timeout=3)
            assert not early.is_alive() and not early.enabled
            assert not _shared_observer_manager._observers
            abandoned = root / "abandoned" / "blocked"
            abandoned.mkdir(parents=True)
            subprocess.run([sys.executable, __file__, "--abandon", str(abandoned)],
                           check=True, timeout=10)
            abandoned_pid = int((abandoned / "child-pid").read_text())
            def reaped_or_exited():
                try:
                    return psutil.Process(abandoned_pid).status() == psutil.STATUS_ZOMBIE
                except psutil.NoSuchProcess:
                    return True
            until(reaped_or_exited, seconds=3)
            print("Parent EOF during blocked recursive start closes native child")
        finally:
            for watcher in watchers:
                watcher.stop()
            for watcher in watchers:
                watcher.join(timeout=3)
    print("PASS: startup cancellation, shared subscription, independent paths, stop-before-start; no child leaks")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        abandon_parent(Path(sys.argv[2]))
    else:
        main()
