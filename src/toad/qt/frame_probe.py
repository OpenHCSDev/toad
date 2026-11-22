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

And one `spent` line: the span's costliest outermost Qt events, each as
`Type/ReceiverClass deliveries x total ms`, then every paint event's count and time. Qt paints
a window's widgets and shows the frame inside the `UpdateRequest` it delivers to the window, so
that row's time less the paints' is what showing the frames cost. A `frames` line splits
the frames by how much of the window the box around their paints covers (`FRAME_SIZES`), each
with its mean time and its mean time without the paints. A `display` line, once for each
window, says what its frames are drawn into and shown on. A `loop` line names the costliest
asyncio work the same way: each coroutine's steps and each plain callback's runs.

The probe only observes; nothing reads its numbers back into the app.
"""

from __future__ import annotations

import asyncio
import gc
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QFontMetricsF, QImage
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
        self.displayed: set[int] = set()
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
        # Each outermost event's deliveries and their time, by event type and receiver class.
        self.costs: dict[tuple, list] = {}
        # Every paint event delivered, at any depth: how many, and their time.
        self.paints = [0, 0.0]
        # The frames shown, by how much of the window the box around their paints covers:
        # each size's frames, their whole time and the time of their paints.
        self.frames = [[0, 0.0, 0.0] for _size in self.FRAME_SIZES]
        # Each asyncio callback's runs and their time, by what it runs (`TimedHandles.runs`).
        self.callbacks: dict[object, list] = {}
        self.frame_box, self.frame_paint_ms, self.frame_window = QRect(), 0.0, 1

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
        self.sink.write(f"{time.time():.3f} {self.spent_line()}\n")
        self.sink.write(f"{time.time():.3f} {self.frames_line()}\n")
        self.sink.write(f"{time.time():.3f} {self.loop_line()}\n")
        self.window_start = now
        self.reset()

    COSTLIEST = 6
    FRAME_SIZES = ((0.1, "small"), (0.5, "mid"), (2.0, "large"))
    """A frame's size is the share of its window the box around everything it painted covers:
    under a tenth, under half, or more. Qt uploads that box to the GPU to show the frame, so
    two small paints far apart (a tab title, a ribbon at the bottom) make a large frame."""

    def painted(self, widget: QWidget, event: QEvent, took_ms: float) -> None:
        """A widget painted inside the frame being shown."""
        # Qt's own answer: some Toad widgets keep the app in an attribute named `window`.
        window = QWidget.window(widget)
        self.frame_box = self.frame_box.united(QRect(widget.mapTo(window, event.rect().topLeft()), event.rect().size()))
        self.frame_window = max(1, window.width() * window.height())
        self.frame_paint_ms += took_ms

    def frame_shown(self, window: QObject, took_ms: float) -> None:
        """A window's UpdateRequest ended: the frame it painted and showed."""
        if id(window) not in self.displayed and isinstance(window, QWidget):
            self.displayed.add(id(window))
            self.sink.write(f"{time.time():.3f} {self.display_line(window)}\n")
        share = self.frame_box.width() * self.frame_box.height() / self.frame_window
        size = next(index for index, (under, _name) in enumerate(self.FRAME_SIZES) if share < under)
        frames = self.frames[size]
        frames[0] += 1
        frames[1] += took_ms
        frames[2] += self.frame_paint_ms
        self.frame_box, self.frame_paint_ms = QRect(), 0.0

    @staticmethod
    def display_line(window: QWidget) -> str:
        """What a window's frames are drawn into and shown on, written once for each window:
        its pixel ratio, the screen's logical DPI and the window font's size in points and
        its line height in Qt's pixels, the screen's refresh rate and depth, the swap
        interval its surface was asked for and got, the surface's colour sizes, and the backing store Qt paints into (its pixel
        format decides whether showing a frame converts the whole picture first)."""
        handle = window.windowHandle()
        if handle is None:
            return f"display window={type(window).__name__} has no native window"
        screen, asked, got = handle.screen(), handle.requestedFormat(), handle.format()
        store = window.backingStore()
        painted = store.paintDevice() if store is not None else None
        pixels = "none" if painted is None else (
            f"{painted.format().name if isinstance(painted, QImage) else type(painted).__name__} "
            f"depth={painted.depth()} {painted.width()}x{painted.height()}")
        return (f"display window={type(window).__name__} {window.width()}x{window.height()} "
                f"ratio={window.devicePixelRatioF():.3f} logical_dpi={screen.logicalDotsPerInch():.1f} "
                f"font={window.font().pointSizeF():.1f}pt/{QFontMetricsF(window.font()).height():.2f}px "
                f"screen={screen.refreshRate():.0f}Hz depth={screen.depth()} "
                f"surface={handle.surfaceType().name} swap_interval asked={asked.swapInterval()} got={got.swapInterval()} "
                f"rgba={got.redBufferSize()}/{got.greenBufferSize()}/{got.blueBufferSize()}/{got.alphaBufferSize()} "
                f"backing_store={pixels}")

    def frames_line(self) -> str:
        """Each frame size's count, mean time and the mean time left once its paints are
        taken out: what showing a frame of that size cost."""
        return "frames " + " | ".join(
            f"{name} {count}x {took / count:.1f}ms show {(took - painted) / count:.1f}ms" if count else f"{name} 0x"
            for (_under, name), (count, took, painted) in zip(self.FRAME_SIZES, self.frames))

    def spent(self, kind: QEvent.Type, receiver: QObject, took_ms: float) -> None:
        """An outermost event was delivered: its whole time, nested events included."""
        cost = self.costs.get((kind, type(receiver)))
        if cost is None:
            cost = self.costs[kind, type(receiver)] = [0, 0.0]
        cost[0] += 1
        cost[1] += took_ms

    def spent_line(self) -> str:
        """Where the span's time went, by the event Qt delivered: the costliest outermost
        events, each `Type/Receiver deliveries x total ms`, then every paint event's share.
        Qt paints and shows a window inside the UpdateRequest it delivers to it, so that
        row's time less the paints' is what showing the frame cost."""
        costliest = sorted(self.costs.items(), key=lambda cost: -cost[1][1])[:self.COSTLIEST]
        rows = " | ".join(f"{kind.name}/{receiver.__name__} {count}x {took:.0f}ms"
                          for (kind, receiver), (count, took) in costliest)
        return f"spent {rows or '(nothing)'} ; paints {self.paints[0]}x {self.paints[1]:.0f}ms"

    def ran(self, what: object, took_ms: float) -> None:
        """An asyncio callback ran on this thread: a coroutine's step, or a plain callback."""
        cost = self.callbacks.get(what)
        if cost is None:
            cost = self.callbacks[what] = [0, 0.0]
        cost[0] += 1
        cost[1] += took_ms

    @staticmethod
    def named(what: object) -> str:
        """A coroutine's code or a callback's function, by its qualified name."""
        return getattr(what, "co_qualname", None) or getattr(what, "__qualname__", None) or type(what).__name__

    def loop_line(self) -> str:
        """The span's costliest asyncio work: each coroutine's steps (or plain callback's
        runs) as `name runs x total ms`, and every callback's count and time. qasync runs
        them from Qt timer events, which the `spent` line shows only as `Timer/_SimpleTimer`."""
        costliest = sorted(self.callbacks.items(), key=lambda cost: -cost[1][1])[:self.COSTLIEST]
        rows = " | ".join(f"{self.named(what)} {count}x {took:.0f}ms" for what, (count, took) in costliest)
        runs = sum(count for count, _took in self.callbacks.values())
        total = sum(took for _count, took in self.callbacks.values())
        return f"loop {rows or '(nothing)'} ; callbacks {runs}x {total:.0f}ms"

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
            if kind is QEvent.Type.Paint:
                probe.paints[0] += 1
                probe.paints[1] += took
                if isinstance(receiver, QWidget):
                    probe.painted(receiver, event, took)
            if not ProbedApplication.depth:
                probe.spent(kind, receiver, took)
                if kind is QEvent.Type.UpdateRequest:
                    probe.frame_shown(receiver, took)
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
                probe.ran(cls.runs(handle), took)
                if took > probe.SLOW_MS:
                    probe.slow(took, cls.describe(handle))

        asyncio.Handle._run = timed_run  # type: ignore[method-assign]

    @staticmethod
    def runs(handle: asyncio.Handle) -> object:
        """What a handle runs, as one thing to count by: a task's step is its coroutine's
        code (every task running the same coroutine function counts together), any other
        callback is its function."""
        callback = handle._callback  # the handle's own record of what it runs
        task = getattr(callback, "__self__", None)
        if isinstance(task, asyncio.Task):
            return getattr(task.get_coro(), "cr_code", task)
        return getattr(callback, "__func__", callback)

    @staticmethod
    def describe(handle: asyncio.Handle) -> str:
        callback = handle._callback  # the handle's own record of what it runs
        task = getattr(callback, "__self__", None)
        if isinstance(task, asyncio.Task):
            coroutine = task.get_coro()
            return f"task={task.get_name()} coroutine={getattr(coroutine, '__qualname__', coroutine)}"
        return f"callback={getattr(callback, '__qualname__', repr(callback))}"
