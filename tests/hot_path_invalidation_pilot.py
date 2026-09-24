"""Fast projection paths still observe updates and coalesce directory reloads."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp, reveal_project_tree
from toad.widgets.agent_response import AgentResponse


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-hot-invalidation-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        comms.register(Thread("worker", frozenset({"team"}), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            screen._coordination_root = str(comms.root.resolve())
            screen._comms_thread = "worker"
            await screen.conversation.contents.mount(*[
                AgentResponse("\n".join(f"- item {j}" for j in range(20))) for _ in range(20)
            ])
            await pilot.pause()
            assert screen._project_panel.directory_tree is None
            with patch.object(screen, "query_one_optional", side_effect=AssertionError("full-screen search")):
                for _ in range(100):
                    await screen.on_project_directory_update()
            assert screen._project_panel.directory_tree is None
            app._sidebar_snapshot = comms.viewer_snapshot(str(root))
            with patch.object(app.coordination_wire, "thread_views", side_effect=AssertionError("UI wire scan")), \
                 patch.object(app.coordination_wire.registry, "_load", side_effect=AssertionError("UI registry read")):
                for _ in range(100):
                    assert app.open_tabs[0].title.endswith("worker")

            tree = await reveal_project_tree(app, pilot)
            started, release = asyncio.Event(), asyncio.Event()
            calls = []

            async def reload():
                calls.append(True)
                started.set()
                await release.wait()

            with patch.object(tree, "reload", reload):
                for _ in range(100):
                    await screen.on_project_directory_update()
                async with asyncio.timeout(5):
                    await started.wait()
                assert len(calls) == 1
                for _ in range(100):
                    await screen.on_project_directory_update()
                await pilot.pause()
                assert len(calls) == 1, "Directory bursts cancelled/restarted the live loader"
                release.set()
                async with asyncio.timeout(5):
                    while tree._directory_dirty or tree._refresh_scheduled:
                        await pilot.pause(.02)
                assert len(calls) == 2, "Changes received during reload were lost or duplicated"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("hot paths: no missing-tree scans or tab I/O; directory bursts coalesce without lost changes")


if __name__ == "__main__":
    asyncio.run(main())
