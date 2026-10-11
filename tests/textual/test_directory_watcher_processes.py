"""Textual-facing: DirectoryWatcher delivers to a Textual widget's core-event stream while its native observer processes start, share and cancel."""

import subprocess
import sys
import threading
from multiprocessing.connection import Connection
from unittest.mock import patch

import psutil

import support.watchers
from support.watchers import RecordingWatcher, abandon_parent, blocked_observe_path, stop, until
from toad.directory_watcher import _ChangeSignal, _ObserverReady, _observe_path, _shared_observer_manager


def test_cancelling_a_blocked_start_leaves_the_other_subscribers_and_directories_alone(tmp_path):
    blocked, healthy = tmp_path / "blocked", tmp_path / "healthy"
    blocked.mkdir()
    healthy.mkdir()
    watchers = []
    try:
        with patch("toad.directory_watcher._observe_path", blocked_observe_path):
            waiting = RecordingWatcher(blocked)
            watchers.append(waiting)
            waiting.start()
            until(lambda: (blocked / "entered-recursive-walk").exists(), "the blocked recursive walk")
            assert not waiting.enabled
            pid = waiting._observation.process.pid
            first, second = RecordingWatcher(healthy), RecordingWatcher(healthy)
            watchers.extend((first, second))
            first.start()
            second.start()
            until(lambda: first.enabled and second.enabled, "both healthy watchers enabled")
            assert first._observation is second._observation
            healthy_pid = first._observation.process.pid
            (healthy / "first").touch()
            assert first.received.wait(3) and second.received.wait(3)
            stop(waiting)
            assert not psutil.pid_exists(pid), "Cancelled startup left a child"
            stop(first)
            assert second.enabled and psutil.pid_exists(healthy_pid)
            second.received.clear()
            (healthy / "second").touch()
            assert second.received.wait(3)
            stop(second)
            assert not psutil.pid_exists(healthy_pid)
            assert not _shared_observer_manager._observers
    finally:
        for watcher in watchers:
            watcher.stop()
        for watcher in watchers:
            watcher.join(timeout=3)


def test_a_watcher_stopped_before_it_starts_never_observes(tmp_path):
    early = RecordingWatcher(tmp_path)
    try:
        early.stop()
        early.start()
        early.join(timeout=3)
        assert not early.is_alive() and not early.enabled
        assert not _shared_observer_manager._observers
    finally:
        early.stop()
        early.join(timeout=3)


def test_an_owner_that_dies_during_a_blocked_start_takes_its_observer_with_it(tmp_path):
    abandoned = tmp_path / "abandoned" / "blocked"
    abandoned.mkdir(parents=True)
    subprocess.run([sys.executable, support.watchers.__file__, "--abandon", str(abandoned)],
                   check=True, timeout=10)
    pid = int((abandoned / "child-pid").read_text())

    def reaped_or_exited():
        try:
            return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return True

    until(reaped_or_exited, "the observer exited", seconds=3)


def overlapping_observe_path(path, owner):
    """The observer process whose readiness message stays in flight until a native event is dispatched."""
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
        # With no shared send lock a second writer would be observable here,
        # even when small OS pipe writes happen to avoid corruption in a run.
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

    with patch.object(Connection, "send", checked_send), patch.object(_ChangeSignal, "on_any_event", dispatch):
        _observe_path(path, owner)


def test_a_native_burst_during_readiness_is_delivered_without_concurrent_pipe_writers(tmp_path):
    watched, control = tmp_path / "watched", tmp_path / "control"
    watched.mkdir()
    control.mkdir()
    watcher = RecordingWatcher(watched)
    try:
        with patch("toad.directory_watcher._observe_path", overlapping_observe_path):
            watcher.start()
            until(lambda: (control / "ready-thread").exists(), "the readiness message in flight")
            pid = watcher._observation.process.pid
            for index in range(200):
                (watched / f"burst-{index}").touch()
            until(lambda: watcher.enabled, "the watcher ready")
            assert watcher.received.wait(5), "Burst invalidation was not delivered"
            assert (control / "event-thread").read_text() != (control / "ready-thread").read_text()
            assert not (control / "concurrent-writer").exists()
            watcher.received.clear()
            (watched / "after-readiness").touch()
            assert watcher.received.wait(5), "Delivery stopped after readiness"
            assert not (control / "concurrent-writer").exists()
            stop(watcher)
            assert not psutil.pid_exists(pid)
    finally:
        watcher.stop()
        watcher.join(timeout=3)
