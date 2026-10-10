"""Agent log files, written off the UI thread by one writer for the process.

Every protocol line is logged. A line costs the UI thread only a queue put;
one writer thread drains the queue in batches and keeps each log file open.
A failed write is not lost: the next log call raises it.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import ClassVar, TextIO


class AgentLog:
    """The process's single writer for agent log files."""

    _instance: ClassVar[AgentLog | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        self.lines: queue.SimpleQueue[tuple[Path, str]] = queue.SimpleQueue()
        self.failure: OSError | None = None
        self.files: dict[Path, TextIO] = {}
        threading.Thread(target=self._write, name="agent-log-writer", daemon=True).start()

    @classmethod
    def shared(cls) -> AgentLog:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def append(self, path: Path, line: str) -> None:
        if (failure := self.failure) is not None:
            self.failure = None
            raise failure
        self.lines.put((path, line))

    def _write(self) -> None:
        while True:
            batch = [self.lines.get()]
            while True:
                try:
                    batch.append(self.lines.get_nowait())
                except queue.Empty:
                    break
            touched = set()
            try:
                for path, line in batch:
                    if (file := self.files.get(path)) is None:
                        file = self.files[path] = path.open("at")
                    file.write(f"{line.rstrip()}\n")
                    touched.add(file)
                for file in touched:
                    file.flush()
            except OSError as error:
                self.failure = error
