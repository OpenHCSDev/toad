from __future__ import annotations

import threading
from asyncio import AbstractEventLoop
from dataclasses import dataclass
from queue import Queue
from typing import IO, Callable

from typing_extensions import Final

MAX_QUEUED_WRITES: Final[int] = 30


@dataclass(frozen=True)
class _FlushSignal:
    callback: Callable[[], None]
    loop: AbstractEventLoop

    def deliver(self) -> None:
        """Publish completion to the original application loop, if still alive."""
        try:
            self.loop.call_soon_threadsafe(self.callback)
        except RuntimeError:
            if not self.loop.is_closed():
                raise


class WriterThread(threading.Thread):
    """A thread / file-like to do writes to stdout in the background."""

    def __init__(self, file: IO[str]) -> None:
        super().__init__(daemon=True, name="textual-output")
        self._queue: Queue[str | _FlushSignal | None] = Queue(MAX_QUEUED_WRITES)
        self._file = file

    def write(self, text: str) -> None:
        """Write text. Text will be enqueued for writing.

        Args:
            text: Text to write to the file.
        """
        self._queue.put(text)

    def call_after_flush(self, callback: Callable[[], None], loop: AbstractEventLoop) -> None:
        """Publish on the supplied loop after all earlier queued writes flush."""
        self._queue.put(_FlushSignal(callback, loop))

    def isatty(self) -> bool:
        """Pretend to be a terminal.

        Returns:
            True.
        """
        return True

    def fileno(self) -> int:
        """Get file handle number.

        Returns:
            File number of proxied file.
        """
        return self._file.fileno()

    def flush(self) -> None:
        """Flush the file (a no-op, because flush is done in the thread)."""
        return

    def run(self) -> None:
        """Run the thread."""
        write = self._file.write
        flush = self._file.flush
        get = self._queue.get
        qsize = self._queue.qsize
        # Read from the queue, write to the file.
        # Flush when there is a break.
        while True:
            text: str | _FlushSignal | None = get()
            if text is None:
                break
            if isinstance(text, _FlushSignal):
                flush()
                text.deliver()
                continue
            write(text)
            if qsize() == 0:
                flush()
        flush()

    def stop(self) -> None:
        """Stop the thread, and block until it finished."""
        self._queue.put(None)
        self.join()
