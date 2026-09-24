"""Repeatable workloads for the hot paths identified in the live process profile."""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from statistics import median

from agent_comms import Activity, ActivityState, Thread, wire
from agent_comms.declarations import ActivityLog
from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


def activity_file(path, count=10000):
    now = time.time()
    path.write_text("".join(json.dumps(Activity(f"worker-{i % 24}", ActivityState.WORKING,
                                               f"Step {i}", now).to_wire()) + "\n"
                            for i in range(count)))


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-hot-paths-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        log_path = root / "activity.jsonl"
        activity_file(log_path)
        reader, writer = ActivityLog(log_path), ActivityLog(log_path)
        reader.all_current()
        activity_ms = []
        for index in range(20):
            writer.emit(Activity("worker-0", ActivityState.THINKING, f"New step {index}"))
            start = time.perf_counter()
            assert reader.all_current()["worker-0"].detail == f"New step {index}"
            activity_ms.append((time.perf_counter() - start) * 1000)
        comms = wire(root / "wire")
        for index in range(24):
            comms.register(Thread(f"worker-{index}", frozenset({"team"}), str(root)))
        activity_file(comms.activity._path)
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            await conversation.contents.mount(*[
                AgentResponse(f"Response {i}\n\n" + "\n".join(f"- list item {j}" for j in range(20)))
                for i in range(30)
            ])
            await pilot.pause()
            widgets = len(list(app.screen.walk_children()))
            start = time.perf_counter()
            for _ in range(200):
                await app.screen.on_project_directory_update()
            directory_ms = (time.perf_counter() - start) * 1000
            app._sidebar_snapshot = comms.viewer_snapshot(str(root))
            tabs_ms = []
            for index in range(20):
                comms.set_activity("worker-0", ActivityState.THINKING, f"Change {index}")
                start = time.perf_counter()
                assert app.open_tabs
                tabs_ms.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            for _ in range(30):
                app.screen._refresh_layout(scroll=True)
            layout_ms = (time.perf_counter() - start) * 1000
            assert app._exception is None
            print(json.dumps({"widgets": widgets, "activity_log_records": 10000,
                              "activity_append_read_median_ms": median(activity_ms),
                              "directory_updates_200_ms": directory_ms,
                              "tab_projection_after_append_median_ms": median(tabs_ms),
                              "scroll_layout_30_ms": layout_ms}, indent=2))
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
