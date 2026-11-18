"""A native crash's Python stacks: every thread's, written beside the saved tracebacks.

A fault in C (a segfault in the interpreter, PySide or a C extension) kills the process
before any Python handler runs, so nothing reaches `paths.save_error`. Python's
`faulthandler` writes each thread's stack from the signal handler itself, into a file that
must already be open. This owner opens that file at a start, before anything native runs,
keeps it open for the life of the process, and removes it at a clean exit when nothing was
written, so the errors folder holds a `fatal_*` file only for a run that crashed.
"""

from __future__ import annotations

import atexit
import faulthandler
import os
from pathlib import Path
from typing import ClassVar, TextIO

from toad import paths


class FatalTrace:
    """The one fault trace of this process. `enabled` is called once by each entry that
    starts a frontend (Android's and desktop Qt's), first thing."""

    PREFIX: ClassVar[str] = "fatal"
    stream: ClassVar[TextIO | None] = None
    path: ClassVar[Path | None] = None

    @classmethod
    def enabled(cls) -> Path:
        """Open this run's trace file and route every fatal signal's stacks into it."""
        if cls.path is None:
            path = paths.get_errors() / paths.generate_datetime_filename(cls.PREFIX, ".txt")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            cls.stream = os.fdopen(descriptor, "w", buffering=1, encoding="utf-8")
            cls.path = path
            faulthandler.enable(cls.stream, all_threads=True)
            atexit.register(cls.closed)
        return cls.path

    @classmethod
    def closed(cls) -> None:
        """A clean exit: stop tracing and drop the file when no fault wrote to it."""
        if cls.stream is None or cls.path is None:
            return
        faulthandler.disable()
        cls.stream.close()
        if cls.path.stat().st_size == 0:
            cls.path.unlink()
        cls.stream = None
        cls.path = None
