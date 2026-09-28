"""Actual watchdog dispatch contends with readiness without concurrent pipe writers."""

import json
import tempfile
import threading
from multiprocessing.connection import Connection
from pathlib import Path
from unittest.mock import patch

import psutil

from toad.directory_watcher import _ChangeSignal, _ObserverReady, _observe_path
from watcher_startup_cancellation import RecordingWatcher, stop, until


def overlapping_observe_path(path, owner):
    control = path.parent / "control"
    event_attempted, sending = threading.Event(), threading.Event()
    send = Connection.send
    on_event = _ChangeSignal.on_any_event

    def dispatch(handler, event):
        if not event_attempted.is_set():
            (control / "event-thread").write_text(str(threading.get_ident()))
            event_attempted.set()
        on_event(handler, event)

    def checked_send(connection, event):
        # Keep the real readiness write in flight until the native dispatch
        # thread enters its handler. With no shared send lock that second
        # writer is observable here, even when small OS pipe writes happen
        # to avoid corruption in a particular run.
        if sending.is_set():
            (control / "concurrent-writer").touch()
            raise AssertionError("Two threads entered Connection.send concurrently")
        sending.set()
        try:
            if isinstance(event, _ObserverReady):
                (control / "ready-thread").write_text(str(threading.get_ident()))
                assert event_attempted.wait(5), "No native event overlapped readiness"
            send(connection, event)
        finally:
            sending.clear()

    with patch.object(Connection, "send", checked_send), patch.object(
        _ChangeSignal, "on_any_event", dispatch
    ):
        _observe_path(path, owner)


def main():
    with tempfile.TemporaryDirectory(prefix="watcher-ready-burst-") as directory:
        root = Path(directory)
        watched, control = root / "watched", root / "control"
        watched.mkdir()
        control.mkdir()
        watcher = RecordingWatcher(watched)
        try:
            with patch("toad.directory_watcher._observe_path", overlapping_observe_path):
                watcher.start()
                until(lambda: (control / "ready-thread").exists())
                pid = watcher._observation.process.pid
                for index in range(200):
                    (watched / f"burst-{index}").touch()
                until(lambda: watcher.enabled)
                assert watcher.received.wait(5), "Burst invalidation was not delivered"
                assert (control / "event-thread").read_text() != (control / "ready-thread").read_text()
                assert not (control / "concurrent-writer").exists()
                watcher.received.clear()
                (watched / "after-readiness").touch()
                assert watcher.received.wait(5), "Delivery stopped after readiness"
                assert not (control / "concurrent-writer").exists()
                duration = stop(watcher)
                assert not psutil.pid_exists(pid)
                print(json.dumps({"native_burst_files": 200, "overlapped_threads": 2,
                                  "concurrent_pipe_writers": 0, "readiness_delivered": True,
                                  "later_delivery": True, "joined_seconds": duration}))
        finally:
            watcher.stop()
            watcher.join(timeout=3)
    print("PASS: real native burst overlaps readiness; delivery and process exit complete")


if __name__ == "__main__":
    main()
