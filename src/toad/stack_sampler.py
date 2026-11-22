"""Where a thread's Python is, sampled from another thread."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import Counter
from pathlib import Path

class StackSampler(threading.Thread):
    """Where one thread's Python is, read from another thread every `EVERY` seconds: a
    frontend's frame probe names what held the thread that draws.

    `sys._current_frames` answers each thread's innermost Python frame without stopping it.
    While the thread runs native code (an event loop waiting, a toolkit's paint or layout),
    its innermost Python frame is the one that called into it, so those samples name that
    caller: the frame that entered the event loop for waiting and for work the toolkit
    started itself, a Toad function for a native call it made.
    """

    EVERY = 0.004
    NAMED = 14

    def __init__(self, thread: int) -> None:
        super().__init__(name="stack-sampler", daemon=True)
        self.thread = thread
        self.samples = 0
        self.leaves: Counter[str] = Counter()
        self.within: Counter[str] = Counter()
        self.counted = threading.Lock()
        self.start()

    @staticmethod
    def named(code) -> str:
        return f"{Path(code.co_filename).stem}.{code.co_qualname}"

    def run(self) -> None:
        marker = f"{os.sep}toad{os.sep}"
        while True:
            time.sleep(self.EVERY)
            names = self.read(marker)
            if names is None:
                return
            leaf, within = names
            with self.counted:
                self.samples += 1
                self.leaves[leaf] += 1
                self.within[within] += 1

    def read(self, marker: str) -> tuple[str, str] | None:
        """The names only, with no frame kept past this call. A frame object still referenced
        when its function returns keeps that call's locals alive, and a paint's local is its
        QPainter: a sampler that held one frame across its sleep left painters open on
        widgets Qt had finished painting, and Qt crashed in its next timer. Nothing here
        waits, so the sampled thread does not run between the frame being read and released."""
        frame = sys._current_frames().get(self.thread)
        if frame is None:
            return None
        leaf = self.named(frame.f_code)
        while frame is not None and marker not in frame.f_code.co_filename:
            frame = frame.f_back
        within = self.named(frame.f_code) if frame is not None else "(none)"
        del frame
        return leaf, within

    def taken(self) -> tuple[str, ...]:
        """The span's two lines, and a fresh count."""
        with self.counted:
            samples, leaves, within = self.samples, self.leaves, self.within
            self.samples, self.leaves, self.within = 0, Counter(), Counter()
        if not samples:
            return ()

        def shares(counts: Counter[str]) -> str:
            return " ".join(f"{name}:{100 * count // samples}" for name, count in counts.most_common(self.NAMED))
        return (f"samples={samples} leaf% {shares(leaves)}", f"samples={samples} toad% {shares(within)}")
