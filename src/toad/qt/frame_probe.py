"""How responsive the GUI thread is, measured where it runs: off unless asked for.

`TOAD_FRAME_PROBE=1` in the environment, or a `frame-probe` file in Toad's state folder,
starts one probe for the process. A phone without a shell environment asks for it with
`adb shell run-as org.toadcomms.toadcomms touch files/state/toad/frame-probe` and a relaunch;
the probe then writes to `files/state/toad/logs/frame-probe.log` (on a desktop,
`<XDG_STATE_HOME>/toad/logs/frame-probe.log`). Every few seconds it writes a summary line:

- **stalls**: a 10 ms timer's lateness. Every tick that arrives more than a frame late is
  time the event loop spent elsewhere, so the largest lateness is the worst stall a
  scroll or an animation suffered;
- **collector pauses**: each of Python's garbage collections, timed from start to stop;
- **key latency**: from a key press or a soft keyboard's input-method event reaching the
  application to the next paint of the widget it was delivered to, which is when the typed
  glyph is on screen.

And it writes one `slow` line for every piece of work over `SLOW_MS` that held the thread,
naming what it was, so a stall in the summary has its cause beside it:

- a **Qt event** delivered to a receiver (a tap, a key, a paint, a resize), timed over its
  whole delivery by `ProbedApplication.notify`, with the receiver's class and object name;
- an **asyncio callback** (qasync runs them from Qt timer events), timed by `TimedHandles`,
  naming the task (an operation's task is named for its `OperationKind`) and its coroutine.

A delivery that contains a slow callback, or a slow nested delivery, is written after it, so
the innermost named work comes first.

With each summary it writes two `hot` lines from `StackSampler`, a thread that reads the GUI
thread's Python stack every few milliseconds: the functions it was most often in (`leaf`),
and the innermost Toad function on the stack (`toad`), each as a share of the samples. A
sample whose stack ends where Qt's event loop was entered is Qt's own time (waiting, or
painting and laying out in C++), so the line says whether a busy loop is Python or Qt, and
names the Python. It is what a profiler would say, on a phone that has none.

The probe only observes; nothing reads its numbers back into the app.
"""

from __future__ import annotations

import asyncio
import gc
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from toad import paths
from toad.stack_sampler import StackSampler


class FrameProbe(QObject):
    INTERVAL_MS = 10
    REPORT_SECONDS = 5.0
    SLOW_MS = 100.0
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
        ProbedApplication.probe = self
        TimedHandles.install(self)
        self.sampler = StackSampler(threading.get_ident())
        self.timer.start()
        self.sink.write(f"{time.time():.3f} probe started interval_ms={self.INTERVAL_MS} "
                        f"slow_ms={self.SLOW_MS:.0f} events_timed={isinstance(application, ProbedApplication)}\n")

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
        for line in self.sampler.taken():
            self.sink.write(f"{time.time():.3f} hot {line}\n")
        self.window_start = now
        self.reset()

    def slow(self, took_ms: float, what: str) -> None:
        """Work that held the thread past `SLOW_MS`, named."""
        self.sink.write(f"{time.time():.3f} slow {took_ms:.0f}ms {what}\n")

    def collected(self, phase: str, info: dict) -> None:
        """Python's collector paused the thread it ran on: how long, from its start to stop."""
        if phase == "start":
            self.collecting_since = time.perf_counter()
        elif self.collecting_since:
            took = (time.perf_counter() - self.collecting_since) * 1000.0
            self.gc_ms.append(took)
            self.collecting_since = 0.0
            if took > self.SLOW_MS:
                self.slow(took, f"gc generation={info.get('generation')} collected={info.get('collected')}")

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
    def application(cls, arguments: list[str]) -> QApplication:
        """The process's QApplication: one that times each event's delivery when the probe is
        asked for, Qt's own otherwise (a Python `notify` costs every event a call into Python)."""
        return (ProbedApplication if cls.requested() else QApplication)(arguments)

    @classmethod
    def start_if_requested(cls, application: QApplication) -> FrameProbe | None:
        if not cls.requested():
            return None
        return cls(application, paths.get_log() / "frame-probe.log")


class ProbedApplication(QApplication):
    """A QApplication that times each event's whole delivery, so a stall names the event and
    the receiver it was spent in. Made only when the probe is asked for (`FrameProbe.application`)."""

    probe: FrameProbe | None = None
    depth = 0

    def notify(self, receiver: QObject, event: QEvent) -> bool:  # type: ignore[override]
        probe = ProbedApplication.probe
        if probe is None:
            return super().notify(receiver, event)
        kind = event.type()
        started = time.perf_counter()
        ProbedApplication.depth += 1
        try:
            return super().notify(receiver, event)
        finally:
            ProbedApplication.depth -= 1
            took = (time.perf_counter() - started) * 1000.0
            if took > probe.SLOW_MS:
                name = receiver.objectName() if isinstance(receiver, QObject) else ""
                probe.slow(took, f"event={kind.name} receiver={type(receiver).__name__}"
                                 f"{'#' + name if name else ''} depth={ProbedApplication.depth}")


class TimedHandles:
    """Times every asyncio callback the loop runs, naming the slow ones by their task. qasync
    runs callbacks from Qt timer events, so a slow coroutine step shows as a slow Timer event
    to qasync's own object; this names the coroutine and the operation that started it."""

    installed = False

    @classmethod
    def install(cls, probe: FrameProbe) -> None:
        if cls.installed:
            return
        cls.installed = True
        run = asyncio.Handle._run

        def timed_run(handle: asyncio.Handle) -> None:
            started = time.perf_counter()
            try:
                run(handle)
            finally:
                took = (time.perf_counter() - started) * 1000.0
                if took > probe.SLOW_MS:
                    probe.slow(took, cls.describe(handle))

        asyncio.Handle._run = timed_run  # type: ignore[method-assign]

    @staticmethod
    def describe(handle: asyncio.Handle) -> str:
        callback = handle._callback  # the handle's own record of what it runs
        task = getattr(callback, "__self__", None)
        if isinstance(task, asyncio.Task):
            coroutine = task.get_coro()
            return f"task={task.get_name()} coroutine={getattr(coroutine, '__qualname__', coroutine)}"
        return f"callback={getattr(callback, '__qualname__', repr(callback))}"
