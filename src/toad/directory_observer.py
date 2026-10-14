"""The directory observer's own process.

This module is what a spawned observer imports, so it imports only watchdog:
importing Textual or Toad core here costs every spawn seconds of CPU.
"""

from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from multiprocessing.connection import Connection
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

if TYPE_CHECKING:
    from toad.directory_watcher import _PathObservation


class ObserverEvent(ABC):
    @abstractmethod
    def apply(self, observation: "_PathObservation") -> None:
        """Apply a notification from the owned observer process."""


class ObserverReady(ObserverEvent):
    def apply(self, observation: "_PathObservation") -> None:
        observation.ready.set()


class ObserverChanged(ObserverEvent):
    def apply(self, observation: "_PathObservation") -> None:
        observation.dispatcher.on_any_event(FileSystemEvent(str(observation.path)))


class ChangeSignal(FileSystemEventHandler):
    """Only invalidation crosses the pipe; filesystem payload stays in the child."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._send_lock = threading.Lock()

    def notify(self, event: ObserverEvent) -> None:
        with self._send_lock:
            try:
                self.connection.send(event)
            except ConnectionError:
                os._exit(0)  # The parent no longer owns this observer.

    def on_any_event(self, event: FileSystemEvent) -> None:
        self.notify(ObserverChanged())


def watch_owner(owner: Connection) -> None:
    """An exited parent must not leave a recursive scan or native handles alive."""
    try:
        owner.recv_bytes()
    except (EOFError, ConnectionError):
        os._exit(0)


def observe_path(path: Path, owner: Connection) -> None:
    """Own native watch handles in a process cancellable during recursive start."""
    threading.Thread(target=watch_owner, args=(owner,), daemon=True).start()
    observer = Observer()
    if isinstance(observer, PollingObserver):
        return
    handler = ChangeSignal(owner)
    observer.schedule(
        handler, str(path), recursive=True,
        event_filter=[
            FileCreatedEvent, FileDeletedEvent, FileMovedEvent,
            DirCreatedEvent, DirDeletedEvent, DirMovedEvent,
        ],
    )
    observer.start()
    handler.notify(ObserverReady())
    # The parent owns this process through the last subscriber. Terminating
    # it closes all native handles even when observer.start() is still walking.
    threading.Event().wait()
