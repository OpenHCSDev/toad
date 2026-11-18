"""Measure scrolling cost in the Qt conversation tab, offscreen, on the live bus.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m tools.qt_scroll_profile \
        PROFILE OUTDIR [--profile]

Opens #comms exactly as the client does, loads several older pages, then drives the
interactions a reader does on a phone and times each frame: the total frame time (the
layout-and-paint of one scrolled frame) and the input-to-paint latency (from dispatching
one input to its painted frame). It reports median and p95 in milliseconds for each of:

  fling        a kinetic fling's decaying positions
  wheel        a burst of wheel steps that reverses partway
  pageup       scrolling to the top so older pages load
  arrival      new messages admitted while the reader is scrolled up

With --profile the same interactions run under cProfile and the top callers by cumulative
time print, so the frame owner is ranked, not guessed. Timings themselves are read from a
plain (unprofiled) run so the before/after numbers are wall-clock, equally warm.
"""

from __future__ import annotations

import asyncio
import cProfile
import json
import os
import pstats
import statistics
import sys
import time
from io import StringIO
from pathlib import Path

import qasync
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from agent_comms.projects.checkouts import Checkout
from toad.client.connection import RemoteCoreConnection
from toad.client.history import WirePageBuffer
from toad.qt.client_start import open_app
from toad.qt.glyph_fonts import install_glyph_fonts
from toad.qt.theme import current_scheme

from tools.qt_drive import ConversationRow, until

PROJECT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 412, 915  # the Pixel 8a at its device pixel ratio


def pct(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def summary(name: str, frames: list[float], latencies: list[float]) -> dict:
    return {
        "name": name,
        "frames": len(frames),
        "frame_ms_median": round(statistics.median(frames), 3) if frames else 0.0,
        "frame_ms_p95": round(pct(frames, 0.95), 3),
        "latency_ms_median": round(statistics.median(latencies), 3) if latencies else 0.0,
        "latency_ms_p95": round(pct(latencies, 0.95), 3),
    }


class ScrollDrive:
    """Opens #comms, loads pages, and times the reader's scrolling interactions."""

    def __init__(self, app, out: Path) -> None:
        self.app = app
        self.out = out
        self.window = None
        self.history = None

    @property
    def page(self):
        return self.app.workspace_sessions.pages.currentWidget()

    async def open_comms(self) -> None:
        await until(lambda: sum(section.childCount()
                               for section in self.app.workspace_sessions.home.rows.items()) > 0,
                    "welcome rows")
        self.app.resize(WIDTH, HEIGHT)
        for item in self.app.sidebar.items():
            item.setExpanded(item.key == "#comms" or item.isExpanded())
        self.app.sidebar.present()
        await asyncio.sleep(0.3)
        comms = next(row for row in self.app.sidebar.items()
                     if isinstance(row, ConversationRow) and row.target.name == "#comms")
        self.app.open_row(comms)
        await until(lambda: self.page is not self.app.workspace_sessions.home
                    and self.page.messages.model_rows.rowCount(), "#comms rows")
        await asyncio.sleep(1.0)
        self.window = self.page.messages
        self.history = self.page.message_history
        self.app.resize(WIDTH, HEIGHT)
        await asyncio.sleep(0.5)

    async def load_older(self, pages: int = 5) -> None:
        """Scroll to the top repeatedly so older pages load: a deep window to scroll in."""
        for _ in range(pages):
            before = self.window.model_rows.fragments[0].key
            self.window.scroll_y = 0
            try:
                await until(lambda: self.window.model_rows.fragments[0].key != before,
                            "older", tenths=40)
            except TimeoutError:
                break
            await asyncio.sleep(0.3)
        self.window.scroll_y = self.window.max_scroll_y
        await asyncio.sleep(0.5)

    def frame(self) -> float:
        """Force one synchronous layout-and-paint of the viewport; return its milliseconds."""
        start = time.perf_counter()
        self.window.viewport().grab()
        return (time.perf_counter() - start) * 1000.0

    def at_scroll(self, value: float) -> tuple[float, float]:
        """Apply one scroll position as input, flush the frame, and time both."""
        start = time.perf_counter()
        self.window.scroll_y = value
        QApplication.processEvents()
        frame = self.frame()
        latency = (time.perf_counter() - start) * 1000.0
        return frame, latency

    def fling_positions(self) -> list[float]:
        """A kinetic fling upward then settling: decaying velocity over ~1s of frames."""
        top, bottom = 0.0, float(self.window.max_scroll_y)
        position = bottom
        velocity = -(bottom - top) / 12.0  # cover a good stretch, then decay
        positions = []
        for _ in range(60):
            velocity *= 0.92
            position = max(top, min(bottom, position + velocity))
            positions.append(position)
        return positions

    async def measure_fling(self) -> dict:
        self.window.scroll_y = self.window.max_scroll_y
        QApplication.processEvents()
        frames, latencies = [], []
        for value in self.fling_positions():
            frame, latency = self.at_scroll(value)
            frames.append(frame)
            latencies.append(latency)
        return summary("fling", frames, latencies)

    async def measure_wheel(self) -> dict:
        """A wheel burst that reverses partway: Qt routes each step through wheelEvent."""
        viewport = self.window.viewport()
        self.window.scroll_y = self.window.max_scroll_y / 2
        QApplication.processEvents()
        frames, latencies = [], []
        for step in range(24):
            delta = -120 if step < 12 else 120  # scroll up, then reverse
            start = time.perf_counter()
            event = QWheelEvent(QPointF(viewport.rect().center()), QPointF(viewport.mapToGlobal(viewport.rect().center())),
                                QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(viewport, event)
            QApplication.processEvents()
            frame = self.frame()
            frames.append(frame)
            latencies.append((time.perf_counter() - start) * 1000.0)
        return summary("wheel", frames, latencies)

    async def measure_pageup(self) -> dict:
        """Scroll to the top so older pages load; time the frames the loads land in."""
        frames, latencies = [], []
        for _ in range(6):
            before = self.window.model_rows.fragments[0].key
            start = time.perf_counter()
            self.window.scroll_y = 0
            try:
                await until(lambda: self.window.model_rows.fragments[0].key != before,
                            "older", tenths=40)
            except TimeoutError:
                break
            frame = self.frame()
            frames.append(frame)
            latencies.append((time.perf_counter() - start) * 1000.0)
            await asyncio.sleep(0.2)
        return summary("pageup", frames, latencies)

    async def measure_arrival(self) -> dict:
        """New messages while the reader is scrolled up: the newest page re-publishes its
        rows, which is exactly what one wire arrival runs. Time the frame and the reader's
        displacement (a jump the reader would see)."""
        self.window.scroll_y = self.window.max_scroll_y * 0.4
        QApplication.processEvents()
        newest = self.history.pages[-1]
        frames, latencies, jumps = [], [], []
        for _ in range(12):
            before = self.window.scroll_y
            start = time.perf_counter()
            newest.range_changed()
            QApplication.processEvents()
            frame = self.frame()
            frames.append(frame)
            latencies.append((time.perf_counter() - start) * 1000.0)
            jumps.append(abs(self.window.scroll_y - before))
            await asyncio.sleep(0.05)
        result = summary("arrival", frames, latencies)
        result["reader_jump_px_median"] = round(statistics.median(jumps), 1) if jumps else 0.0
        result["reader_jump_px_max"] = round(max(jumps), 1) if jumps else 0.0
        return result

    async def run(self) -> list[dict]:
        await self.open_comms()
        results = []
        # Page up first, from a fresh tail: each older page that lands is a measured frame,
        # and it leaves a deep window for the flings that follow to scroll through.
        results.append(await self.measure_pageup())
        results.append(await self.measure_fling())
        results.append(await self.measure_wheel())
        results.append(await self.measure_arrival())
        return results


MARKED: list = []


async def _record_mark(buffer, page) -> None:
    MARKED.append(page)


async def run(profile: Path, out: Path, do_profile: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    WirePageBuffer.mark_page = _record_mark
    app = await open_app(RemoteCoreConnection.read(profile), Checkout(PROJECT), current_scheme(os.environ))
    drive = ScrollDrive(app, out)
    try:
        if do_profile:
            # Warm the window to a deep, scrolled-up state, then profile the interactions.
            await drive.open_comms()
            await drive.load_older()
            profiler = cProfile.Profile()
            profiler.enable()
            await drive.measure_fling()
            await drive.measure_wheel()
            await drive.measure_arrival()
            profiler.disable()
            stream = StringIO()
            stats = pstats.Stats(profiler, stream=stream).sort_stats("cumulative")
            stats.print_stats(35)
            text = stream.getvalue()
            (out / "profile.txt").write_text(text)
            print(text, flush=True)
            tottime = StringIO()
            pstats.Stats(profiler, stream=tottime).sort_stats("tottime").print_stats(25)
            (out / "profile-tottime.txt").write_text(tottime.getvalue())
            print(tottime.getvalue(), flush=True)
        else:
            results = await drive.run()
            (out / "scroll-metrics.json").write_text(json.dumps(results, indent=2))
            for item in results:
                print(json.dumps(item), flush=True)
    finally:
        app.close()
        await app.close_client()
        QApplication.quit()


def main(arguments: list[str]) -> None:
    args = [a for a in arguments[1:] if not a.startswith("--")]
    if len(args) != 2:
        raise SystemExit(f"usage: {arguments[0]} PROFILE OUTDIR [--profile]")
    install_glyph_fonts(QApplication(arguments[:1]))  # the entry's splash registers them; this profile has none
    qasync.run(run(Path(args[0]), Path(args[1]), "--profile" in arguments))


if __name__ == "__main__":
    main(sys.argv)
