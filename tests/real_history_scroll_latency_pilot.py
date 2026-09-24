"""Read the first five real #any histories into an isolated, attachment-free UI.

Source wire operations are read-only. The test UI has a separate empty wire,
no live ACP attachments, and no sidebar polling; results are history-rendering
measurements, not a complete live-agent/UI latency guarantee.
"""

import asyncio
import cProfile
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
from unittest.mock import patch

from agent_comms import Comms
from scroll_select_latency_pilot import PaintProbe
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    source = Comms(Path(os.environ.get("TOAD_SOURCE_WIRE", "~/.agent-comms")).expanduser())
    views = await asyncio.to_thread(source.channel_views)
    thread_count = int(os.environ.get("TOAD_REAL_THREADS", "5"))
    page_steps = int(os.environ.get("TOAD_REAL_PAGE_STEPS", "4"))
    names = next(view.members for view in views if view.channel.name == "#any")[:thread_count]
    assert len(names) == thread_count, (thread_count, names)
    profile_path = os.environ.get("TOAD_REAL_SCROLL_PROFILE")
    profiler = cProfile.Profile() if profile_path else None

    async def skip_snapshot(self, revision):
        self._snapshot_pending = False

    with tempfile.TemporaryDirectory(prefix="toad-real-history-perf-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = PaintProbe(project_dir=str(root))
        with patch.object(CommsSidebar, "_read_snapshot", skip_snapshot):
            async with app.run_test(size=(120, 40)) as pilot:
                app.settings.set("ui.auto_copy", False)
                await pilot.pause()
                modes = [app.current_mode]
                for _ in names[1:]:
                    await app.new_session_screen(app.get_main_screen)
                    modes.append(app.current_mode)
                for name, mode in zip(names, modes):
                    await app.switch_mode(mode)

                    async def load(*, _name=name, **kwargs):
                        return await asyncio.to_thread(source.thread_transcript_page, _name, **kwargs)

                    page = await load()
                    history = TranscriptHistory(page, load)
                    view = app.screen.conversation
                    await view.post(history)
                    view.window.anchor()
                    await pilot.pause()

                for name, mode in zip(names, modes):
                    await app.switch_mode(mode)
                    await pilot.pause()
                    view = app.screen.conversation
                    window = view.window
                    history = view.contents.query_one(TranscriptHistory)
                    for depth in range(page_steps):
                        async with asyncio.timeout(20):
                            while history._loading:
                                await pilot.pause(.02)
                        # At each depth, move within the current mounted page
                        # as well as toward its paging edge; no render freezing.
                        measurements = []
                        for index in range(12):
                            delta = -2 if index % 2 == 0 else 2
                            if not 0 <= window.scroll_y + delta <= window.max_scroll_y:
                                delta = -delta
                            if not 0 <= window.scroll_y + delta <= window.max_scroll_y:
                                continue
                            painted = app.next_paint = asyncio.get_running_loop().create_future()
                            start = time.perf_counter()
                            if profiler is not None:
                                profiler.enable()
                            window.scroll_relative(y=delta, animate=False, immediate=True)
                            measurements.append((await asyncio.wait_for(painted, 20) - start) * 1000)
                            if profiler is not None:
                                profiler.disable()
                            app.next_paint = None
                        print(json.dumps({"thread": name, "older_page_steps": depth,
                                          "source_cursor": history.pages[0].page.before.offset,
                                          "mounted_history_widgets": history.widget_count,
                                          "all_tab_widgets": sum(len(list(app.get_screen_stack(m)[0].walk_children())) for m in modes),
                                          "scroll_samples": len(measurements),
                                          "median_ms": round(statistics.median(measurements), 2) if measurements else None,
                                          "worst_ms": round(max(measurements), 2) if measurements else None,
                                          "live_acp_attached": False,
                                          "sidebar_polling": False}), flush=True)
                        if not history.has_older:
                            break
                        previous = (history.pages[0].page.before.offset, history.pages[0].start)
                        window.scroll_home(animate=False, immediate=True)
                        async with asyncio.timeout(20):
                            while (history._loading or previous ==
                                   (history.pages[0].page.before.offset, history.pages[0].start)):
                                await pilot.pause(.02)
                        await pilot.pause()
                assert app._exception is None
                if profiler is not None:
                    profiler.dump_stats(profile_path)
            await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
