from pathlib import Path
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


class _SharedObserverManager:
    """Manages shared Observer instances to avoid watchdog's limitation of scheduling the same path multiple times."""

    def __init__(self) -> None:
        self._observers: dict[Path, tuple[Observer, _PathEventDispatcher]] = {}
        self._lock = threading.Lock()

    def register(self, path: Path, watcher: "DirectoryWatcher") -> bool:
        """Register a watcher for a path. Creates a shared observer if needed.

        Args:
            path: Path to watch.
            watcher: DirectoryWatcher instance to register.

        Returns:
            True if successfully registered, False otherwise.
        """
        with self._lock:
            if path in self._observers:
                # Reuse existing observer and dispatcher for this path
                observer, dispatcher = self._observers[path]
                dispatcher.add_watcher(watcher)
                return True

            # Create a new observer and dispatcher for this path
            try:
                observer = Observer()
            except Exception:
                return False

            if isinstance(observer, PollingObserver):
                return False

            dispatcher = _PathEventDispatcher(path)
            dispatcher.add_watcher(watcher)

            try:
                observer.schedule(
                    dispatcher,
                    str(path),
                    recursive=True,
                    event_filter=[
                        FileCreatedEvent,
                        FileDeletedEvent,
                        FileMovedEvent,
                        DirCreatedEvent,
                        DirDeletedEvent,
                        DirMovedEvent,
                    ],
                )
                observer.start()
            except Exception:
                return False

            self._observers[path] = (observer, dispatcher)
            return True

    def unregister(self, path: Path, watcher: "DirectoryWatcher") -> None:
        """Unregister a watcher. Stops the observer if no more watchers exist for this path.

        Args:
            path: Path that was being watched.
            watcher: DirectoryWatcher instance to unregister.
        """
        with self._lock:
            if path not in self._observers:
                return

            observer, dispatcher = self._observers[path]
            dispatcher.remove_watcher(watcher)

            # If no more watchers for this path, stop and remove the observer
            if not dispatcher.has_watchers:
                try:
                    observer.stop()
                    observer.join(timeout=1.0)
                except Exception:
                    pass
                del self._observers[path]


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
        self._enabled = False
        self._dirty = False
        self._delivery_lock = threading.Lock()
        super().__init__(name=repr(self))

    @property
    def enabled(self) -> bool:
        """Is the DirectoryWatcher currently watching?"""
        return self._enabled

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
        if not _shared_observer_manager.register(self._path, self):
            return

        self._enabled = True
        self._stop_event.wait()

        _shared_observer_manager.unregister(self._path, self)

    def stop(self) -> None:
        """Stop the watcher."""
        self._stop_event.set()
