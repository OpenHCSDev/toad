"""Measure completed headless frames for left/right sidebar toggles under load."""

import asyncio
import cProfile
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.side_bar import SideBar


class FrameApp(ToadApp):
    CSS_PATH = Path(__file__).resolve().parents[1] / "src/toad/toad.tcss"
    next_frame: asyncio.Future[float] | None = None
    frame_profiler: cProfile.Profile | None = None

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if (self.next_frame is not None and not self.next_frame.done()
                and renderable is not None and not self._batch_count
                and screen is self.screen):
            if self.frame_profiler is not None:
                self.frame_profiler.disable()
            self.next_frame.set_result(time.perf_counter())
        return result


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-sidebar-collapse-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        tags = frozenset(f"team-{index}" for index in range(5))
        for index in range(24):
            comms.register(Thread(f"worker-{index:02}", tags, str(root)))
        app = FrameApp(project_dir=str(root))
        async with app.run_test(size=(120, 42)) as pilot:
            await pilot.pause()
            for _ in range(9):
                await app.new_session_screen(app.get_main_screen)
            conversation = app.screen.conversation
            await conversation.contents.mount(*[
                AgentResponse(f"## Loaded response {index}\n\n" + "paragraph and line\n\n" * 10)
                for index in range(12)
            ])
            await pilot.pause()
            results = {}
            for selector in ("#channels-sidebar", "#thread-sidebar"):
                sidebar = app.screen.query_one(selector, SideBar)
                timings = []
                for index in range(10):
                    painted = app.next_frame = asyncio.get_running_loop().create_future()
                    profile_path = os.environ.get("TOAD_SIDEBAR_PROFILE")
                    if index == 1 and profile_path:
                        app.frame_profiler = cProfile.Profile()
                        app.frame_profiler.enable()
                    start = time.perf_counter()
                    sidebar.toggle()
                    timings.append((await asyncio.wait_for(painted, 5) - start) * 1000)
                    app.next_frame = None
                    if app.frame_profiler is not None:
                        app.frame_profiler.dump_stats(
                            profile_path + ("-channels.pstats" if selector == "#channels-sidebar"
                                            else "-thread.pstats"))
                        app.frame_profiler = None
                    await pilot.pause()
                sorted_times = sorted(timings)
                results[selector] = {
                    "median_ms": round(statistics.median(timings), 1),
                    "p95_ms": round(sorted_times[int(.95 * (len(timings)-1))], 1),
                    "max_ms": round(max(timings), 1),
                }
            print(json.dumps({"boundary": "completed headless _display; not terminal pixels", "tabs": 10,
                              "active_widgets": len(list(app.screen.walk_children())),
                              "toggle_first_paint": results}, indent=2))
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
