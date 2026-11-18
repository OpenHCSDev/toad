"""How responsive the GUI thread is, measured where it runs: off unless asked for.

`TOAD_FRAME_PROBE=1` in the environment, or a `frame-probe` file in Toad's state folder
(how a phone without a shell environment asks for it: `run-as … touch`), starts one probe
for the process. It measures two things and writes a summary line every few seconds to
`<state>/logs/frame-probe.log`:

- **stalls**: a 10 ms timer's lateness. Every tick that arrives more than a frame late is
  time the event loop spent elsewhere, so the largest lateness is the worst stall a
  scroll or an animation suffered;
- **collector pauses**: each of Python's garbage collections, timed from start to stop;
- **key latency**: from a key press or a soft keyboard's input-method event reaching the
  application to the next paint of the widget it was delivered to, which is when the typed
  glyph is on screen.

The probe only observes; nothing reads its numbers back into the app.
"""

from __future__ import annotations

import gc
import os
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from toad import paths


class FrameProbe(QObject):
    INTERVAL_MS = 10
    REPORT_SECONDS = 5.0
    STALL_BUCKETS = (16, 33, 50, 100, 200, 500, 1000)
    INPUT_EVENTS = (QEvent.Type.KeyPress, QEvent.Type.InputMethod)

    def __init__(self, application: QApplication, sink: Path) -> None:
        super().__init__(application)
        self.sink = sink.open("a", buffering=1)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(self.INTERVAL_MS)
        self.timer.timeout.connect(self.ticked)
        self.last = time.perf_counter()
        self.window_start = self.last
        self.reset()
        self.pending_keys: dict[int, float] = {}
        self.collecting_since = 0.0
        gc.callbacks.append(self.collected)
        application.installEventFilter(self)
        self.timer.start()
        self.sink.write(f"{time.time():.3f} probe started interval_ms={self.INTERVAL_MS}\n")

    def reset(self) -> None:
        self.ticks = 0
        self.worst_ms = 0.0
        self.late_ms = 0.0
        self.buckets = [0] * len(self.STALL_BUCKETS)
        self.keys: list[float] = []
        self.gc_ms: list[float] = []

    def ticked(self) -> None:
        now = time.perf_counter()
        late = (now - self.last) * 1000.0 - self.INTERVAL_MS
        self.last = now
        self.ticks += 1
        if late > 0:
            self.late_ms += late
            self.worst_ms = max(self.worst_ms, late)
            for index, bound in enumerate(self.STALL_BUCKETS):
                if late >= bound:
                    self.buckets[index] += 1
        if now - self.window_start >= self.REPORT_SECONDS:
            self.report(now)

    def report(self, now: float) -> None:
        span = now - self.window_start
        busy = 100.0 * self.late_ms / (span * 1000.0)
        stalls = " ".join(f">={bound}:{count}" for bound, count in zip(self.STALL_BUCKETS, self.buckets))
        keys = sorted(self.keys)
        key_line = (f"keys={len(keys)} key_p50={keys[len(keys) // 2]:.1f} key_max={keys[-1]:.1f}"
                    if keys else "keys=0")
        pauses = (f"gc={len(self.gc_ms)} gc_max_ms={max(self.gc_ms):.1f} gc_total_ms={sum(self.gc_ms):.0f}"
                  if self.gc_ms else "gc=0")
        self.sink.write(f"{time.time():.3f} span={span:.1f}s ticks={self.ticks} "
                        f"worst_stall_ms={self.worst_ms:.1f} loop_busy={busy:.0f}% {stalls} {key_line} {pauses}\n")
        self.window_start = now
        self.reset()

    def collected(self, phase: str, info: dict) -> None:
        """Python's collector paused the thread it ran on: how long, from its start to stop."""
        if phase == "start":
            self.collecting_since = time.perf_counter()
        elif self.collecting_since:
            self.gc_ms.append((time.perf_counter() - self.collecting_since) * 1000.0)
            self.collecting_since = 0.0

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        # A hardware key arrives as a key press; a phone's soft keyboard as an input-method
        # event (each letter grows the word being composed, and a space commits it).
        if kind in self.INPUT_EVENTS and isinstance(watched, QWidget):
            self.pending_keys.setdefault(id(watched), time.perf_counter())
        elif kind is QEvent.Type.Paint and self.pending_keys:
            # A text edit paints through its viewport, a child of the widget the key reached.
            widget = watched
            while isinstance(widget, QWidget):
                pressed = self.pending_keys.pop(id(widget), None)
                if pressed is not None:
                    self.keys.append((time.perf_counter() - pressed) * 1000.0)
                    break
                widget = widget.parentWidget()
        return False

    @classmethod
    def requested(cls) -> bool:
        return bool(os.environ.get("TOAD_FRAME_PROBE")) or (paths.get_state() / "frame-probe").is_file()

    @classmethod
    def start_if_requested(cls, application: QApplication) -> FrameProbe | None:
        if not cls.requested():
            return None
        return cls(application, paths.get_log() / "frame-probe.log")
