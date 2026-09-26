"""Measure native spinner frame work; headless results are not terminal FPS."""

import argparse
import asyncio
import json
from pathlib import Path
import statistics
import time
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Static
from toad.widgets.throbber import Throbber


class SpinnerApp(App):
    CSS = "Throbber { height: 1; dock: top; } Static { height: 1fr; }"

    def compose(self) -> ComposeResult:
        yield Throbber()
        yield Static("A stable background below the animated row.\n" * 100)


def summarize(values):
    values = sorted(values)
    return {"count": len(values), "median_ms": statistics.median(values),
            "p95_ms": values[int(.95*(len(values)-1))], "max_ms": max(values)} if values else {}


async def main(args):
    app = SpinnerApp()
    wall, cpu, gaps = [], [], []
    async with app.run_test(size=(args.width, args.height)) as pilot:
        spinner = app.query_one(Throbber)
        spinner.busy = True
        spinner.auto_refresh = 1 / args.fps
        await pilot.pause()
        await asyncio.sleep(.25)
        render = app.screen._compositor_refresh

        def measured():
            started, thread_started = time.perf_counter_ns(), time.thread_time_ns()
            try:
                return render()
            finally:
                wall.append((time.perf_counter_ns()-started)/1e6)
                cpu.append((time.thread_time_ns()-thread_started)/1e6)

        async def heartbeat():
            before = time.perf_counter_ns()
            while True:
                await asyncio.sleep(.002)
                now = time.perf_counter_ns()
                gaps.append((now-before)/1e6)
                before = now

        with patch.object(app.screen, "_compositor_refresh", measured), \
                patch.object(app.screen, "_refresh_layout", wraps=app.screen._refresh_layout) as layouts, \
                patch.object(app.stylesheet, "apply", wraps=app.stylesheet.apply) as styles:
            observer = asyncio.create_task(heartbeat())
            try:
                await asyncio.sleep(args.seconds)
            finally:
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)
            report = {"scope": "headless native compositor work, not terminal/pixel FPS", "seconds": args.seconds,
                      "requested_refresh_fps": args.fps, "frame_budget_ms": 1000/args.fps,
                      "layout_calls": layouts.call_count, "stylesheet_apply_calls": styles.call_count,
                      "frame_wall": summarize(wall), "frame_thread_cpu": summarize(cpu), "loop_gap": summarize(gaps)}
        spinner.busy = False
        assert app._exception is None
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=306)
    parser.add_argument("--height", type=int, default=80)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.width, args.height, args.fps, args.seconds) <= 0:
        parser.error("Dimensions, fps and duration must be positive")
    asyncio.run(main(args))
