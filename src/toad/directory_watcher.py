from pathlib import Path
import os
from multiprocessing import get_context
from multiprocessing.connection import Connection
from abc import ABC, abstractmethod
import rich.repr

import threading

from textual.message import Message
from textual.dom import NoScreen
from textual.widget import Widget


from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
    FileCreatedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent,
)
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver


class DirectoryChanged(Message):
    """The directory was changed."""

    def can_replace(self, message: Message) -> bool:
        return isinstance(message, DirectoryChanged)


class _PathEventDispatcher(FileSystemEventHandler):
    """Dispatches file system events to multiple DirectoryWatcher instances."""

    QUIET_INTERVAL = 0.12

    def __init__(self, path: Path) -> None:
        self._path = path
        self._watchers: set[DirectoryWatcher] = set()
        self._lock = threading.Lock()
        self._pending: threading.Timer | None = None

    def add_watcher(self, watcher: "DirectoryWatcher") -> None:
        """Add a watcher to receive events."""
        with self._lock:
            self._watchers.add(watcher)

    def remove_watcher(self, watcher: "DirectoryWatcher") -> None:
        """Remove a watcher from receiving events."""
        with self._lock:
            self._watchers.discard(watcher)
            if not self._watchers and self._pending is not None:
                self._pending.cancel()
                self._pending = None

    @property
    def has_watchers(self) -> bool:
        """Check if there are any active watchers."""
        with self._lock:
            return bool(self._watchers)

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Coalesce a filesystem burst into one eventual directory update.

        A single rename or write can generate many inotify events, and each
        open tab has its own watcher. The event payload is not consumed by
        DirectoryChanged; one notification after the burst observes the final
        filesystem state without posting N events to every mounted screen.
        """
        with self._lock:
            if not self._watchers or self._pending is not None:
                return
            timer = threading.Timer(self.QUIET_INTERVAL, self._flush, args=(event,))
            timer.daemon = True
            self._pending = timer
            timer.start()

    def _flush(self, event: FileSystemEvent) -> None:
        with self._lock:
            self._pending = None
            watchers = tuple(self._watchers)
        for watcher in watchers:
            watcher.on_any_event(event)


class _ObserverEvent(ABC):
    @abstractmethod
    def apply(self, observation: "_PathObservation") -> None:
        """Apply a notification from the owned observer process."""


class _ObserverReady(_ObserverEvent):
    def apply(self, observation: "_PathObservation") -> None:
        observation.ready.set()


class _ObserverChanged(_ObserverEvent):
    def apply(self, observation: "_PathObservation") -> None:
        observation.dispatcher.on_any_event(FileSystemEvent(str(observation.path)))


class _ChangeSignal(FileSystemEventHandler):
    """Only invalidation crosses the pipe; filesystem payload stays in the child."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._send_lock = threading.Lock()

    def notify(self, event: _ObserverEvent) -> None:
        with self._send_lock:
            try:
                self.connection.send(event)
            except ConnectionError:
                os._exit(0)  # The parent no longer owns this observer.

    def on_any_event(self, event: FileSystemEvent) -> None:
        self.notify(_ObserverChanged())


def _watch_owner(owner: Connection) -> None:
    """An exited parent must not leave a recursive scan or native handles alive."""
    try:
        owner.recv_bytes()
    except (EOFError, ConnectionError):
        os._exit(0)


def _observe_path(path: Path, owner: Connection) -> None:
    """Own native watch handles in a process cancellable during recursive start."""
    threading.Thread(target=_watch_owner, args=(owner,), daemon=True).start()
    observer = Observer()
    if isinstance(observer, PollingObserver):
        return
    handler = _ChangeSignal(owner)
    observer.schedule(
        handler, str(path), recursive=True,
        event_filter=[
            FileCreatedEvent, FileDeletedEvent, FileMovedEvent,
            DirCreatedEvent, DirDeletedEvent, DirMovedEvent,
        ],
    )
    observer.start()
    handler.notify(_ObserverReady())
    # The parent owns this process through the last subscriber. Terminating
    # it closes all native handles even when observer.start() is still walking.
    threading.Event().wait()


class _PathObservation(threading.Thread):
    """One native observer per path; cancellation never waits on recursive IO."""

    def __init__(self, path: Path) -> None:
        super().__init__(name=f"Directory observation: {path}")
        context = get_context("spawn")
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.dispatcher = _PathEventDispatcher(path)
        self.path = path
        self._parent, self._child = context.Pipe()
        self.process = context.Process(
            target=_observe_path, args=(path, self._child),
            name=f"Directory observer: {path}",
        )

    def run(self) -> None:
        try:
            if self.stopped.is_set():
                return
            self.process.start()
            self._child.close()
            while not self.stopped.is_set() and self.process.is_alive():
                if self._parent.poll(0.1):
                    try:
                        event: _ObserverEvent = self._parent.recv()
                    except (EOFError, ConnectionError):
                        break
                    event.apply(self)
        finally:
            self.ready.clear()
            self._child.close()
            self._parent.close()
            if self.process.pid is not None:
                self.process.join(timeout=0.5)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(timeout=0.5)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(timeout=1)
                self.process.close()

    def stop(self) -> None:
        self.stopped.set()


class _SharedObserverManager:
    """Own one observation per directory until its last subscriber leaves."""

    def __init__(self) -> None:
        self._observers: dict[Path, _PathObservation] = {}
        self._lock = threading.Lock()

    def register(self, path: Path, watcher: "DirectoryWatcher") -> _PathObservation:
        with self._lock:
            observation = self._observers.get(path)
            if observation is None:
                observation = _PathObservation(path)
                observation.dispatcher.add_watcher(watcher)
                self._observers[path] = observation
                observation.start()
            else:
                observation.dispatcher.add_watcher(watcher)
            return observation

    def unregister(self, path: Path, watcher: "DirectoryWatcher") -> None:
        with self._lock:
            observation = self._observers[path]
            observation.dispatcher.remove_watcher(watcher)
            if observation.dispatcher.has_watchers:
                return
            del self._observers[path]
            observation.stop()
        # Unrelated directories can register/unregister during child teardown.
        observation.join()


# Global singleton instance
_shared_observer_manager = _SharedObserverManager()


@rich.repr.auto
class DirectoryWatcher(threading.Thread):
    """Watch for changes to a directory, ignoring purely file data changes.

    Multiple DirectoryWatcher instances can watch the same directory without
    triggering watchdog's limitation, as they share a single Observer internally.
    """

    def __init__(self, path: Path, widget: Widget) -> None:
        """

        Args:
            path: Root path to monitor.
            widget: Widget which will receive the `DirectoryChanged` event.
        """
        self._path = path.resolve()
        self._widget = widget
        self._stop_event = threading.Event()
        self._observation: _PathObservation | None = None
        self._dirty = False
        self._delivery_lock = threading.Lock()
        super().__init__(name=repr(self))

    @property
    def enabled(self) -> bool:
        """Is the DirectoryWatcher currently watching?"""
        return (
            self._observation is not None
            and self._observation.ready.is_set()
            and not self._stop_event.is_set()
        )

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Send DirectoryChanged event when the FS is updated.

        Called by the _PathEventDispatcher when file system events occur.
        """
        with self._delivery_lock:
            self._dirty = True
        self.notify_if_visible()

    def notify_if_visible(self) -> None:
        """Deliver one deferred invalidation when a hidden tab becomes active."""
        if self._stop_event.is_set() or not self._widget.is_attached:
            return
        try:
            screen = self._widget.screen
        except NoScreen:
            return
        if not screen.is_active or screen is not self._widget.app.screen:
            return
        with self._delivery_lock:
            if not self._dirty:
                return
            self._dirty = False
        self._widget.post_message(DirectoryChanged())

    def __rich_repr__(self) -> rich.repr.Result:
        yield self._path
        yield self._widget

    def run(self) -> None:
        if self._stop_event.is_set():
            return
        self._observation = _shared_observer_manager.register(self._path, self)
        try:
            self._stop_event.wait()
        finally:
            _shared_observer_manager.unregister(self._path, self)

    def rebind(self, widget: Widget) -> None:
        """Move notification custody without restarting the path observation."""
        with self._delivery_lock:
            self._widget = widget

    def stop(self) -> None:
        """Stop the watcher."""
        self._stop_event.set()
