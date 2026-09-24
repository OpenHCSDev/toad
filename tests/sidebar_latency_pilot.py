"""Measure pointer and update cost with agents repeated across expanded channels."""

import asyncio
import cProfile
import os
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from agent_comms import ActivityState, Thread, wire
from textual import events
from textual.widget import Widget
from toad.app import ToadApp
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar


@dataclass
class HoverSample:
    row: Widget
    painted: asyncio.Future[float]
    started: float | None = None


class HoverProbe(ToadApp):
    CSS_PATH = Path(__file__).resolve().parents[1] / "src/toad/toad.tcss"
    pending_hover: HoverSample | None = None
    profiler: cProfile.Profile | None = None

    def _display(self, screen, renderable):
        pending = self.pending_hover
        if (pending is not None and renderable is not None and not self._batch_count
                and pending.started is not None and "hover" in pending.row.pseudo_classes):
            pending.painted.set_result((time.perf_counter() - pending.started) * 1000)
            self.pending_hover = None
            if self.profiler is not None:
                self.profiler.disable()
        return super()._display(screen, renderable)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-sidebar-latency-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
        )
        comms = wire(root / "wire")
        tags = frozenset(f"team-{index}" for index in range(6))
        for index in range(24):
            comms.register(Thread(f"worker-{index:02}", tags, str(root)))
        app = HoverProbe(project_dir=str(root))
        profile_path = os.environ.get("TOAD_HOVER_PROFILE")
        if profile_path:
            app.profiler = cProfile.Profile()

        def input_dispatched(message):
            pending = app.pending_hover
            if isinstance(message, events.MouseMove) and pending is not None and pending.started is None:
                pending.started = time.perf_counter()
                if app.profiler is not None:
                    app.profiler.enable()

        async with app.run_test(size=(120, 40), message_hook=input_dispatched) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            for group in sidebar.query(ChannelGroup):
                if not group.expanded:
                    group.toggle_members()
            await pilot.pause()
            viewport = sidebar.scroll_containers[0].content_region
            rows = [row for row in sidebar._ordered_rows() if row.region.overlaps(viewport)]
            timings = []
            for row in rows[:7] * 3:
                painted = asyncio.get_running_loop().create_future()
                app.pending_hover = HoverSample(row, painted)
                move = asyncio.create_task(pilot.hover(row))
                timings.append(await asyncio.wait_for(painted, 5))
                await move
            started = time.perf_counter()
            comms.set_activity("worker-01", ActivityState.WORKING, "Changed status")
            await sidebar.sync_sessions()
            update_ms = (time.perf_counter() - started) * 1000
            print({"rendered_rows": len(sidebar._ordered_rows()),
                   "median_hover_ms": statistics.median(timings), "max_hover_ms": max(timings),
                   "status_update_ms": update_ms})
            if app.profiler is not None:
                app.profiler.dump_stats(profile_path)
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
