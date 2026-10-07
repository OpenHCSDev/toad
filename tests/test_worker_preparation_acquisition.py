"""Real native geometry borrows the worker's acquired source and styles."""

import asyncio
import json
import os

from agent_comms.comms import Comms
from textual.content import Content
from textual.color import Color
from textual.selection import SELECT_ALL
from toad.app import ToadApp
from toad.widgets.worker_static import WorkerStatic


def test_geometry_and_independent_source_style_selection(tmp_path, monkeypatch):
    async def mounted():
        project = tmp_path / "project"
        project.mkdir()
        service = Comms(tmp_path / "wire")
        service.messaging.initialize_private_initial_protocol()
        for key in tuple(os.environ):
            if key.startswith("AGENT_COMMS_"):
                monkeypatch.delenv(key)
        for key, value in {
            "AGENT_COMMS_ROOT": service.root, "XDG_CONFIG_HOME": tmp_path / "config",
            "XDG_STATE_HOME": tmp_path / "state", "XDG_DATA_HOME": tmp_path / "data",
            "XDG_CACHE_HOME": tmp_path / "cache",
        }.items():
            monkeypatch.setenv(key, str(value))
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            worker = WorkerStatic(Content.styled("Original native content " * 20, "$accent"))
            worker.styles.width = "auto"
            worker.styles.dock = "top"
            worker.styles.height = 4
            await app.selected_session.mount(worker)

            async def ready():
                await pilot.pause()
                async with asyncio.timeout(20):
                    await worker.wait_ready()
                assert worker.paint_ready and worker.prepared_content is not None

            await ready()
            acquired = worker._wanted.task.source
            for width in (95, 120, 100):
                await pilot.resize_terminal(width, 35)
                await ready()
                assert worker._wanted.task.source is acquired
                assert worker._wanted.task.presentation.options.size.width == width
                assert "Original native content" in worker.prepared_content.text
            worker.styles.color = "red"
            await ready()
            assert worker._wanted.task.presentation.native_style.foreground == Color.parse("red")
            app.screen.selections = {worker: SELECT_ALL}
            await ready()
            assert worker._wanted.task.source.selection is not None
            assert worker.get_selection(SELECT_ALL)[0] == worker._source.value.plain
            worker.update(Content("Changed native content " * 12))
            await ready()
            assert "Changed native content" in worker.prepared_content.text
            assert "Original native content" not in worker.prepared_content.text
            assert app._exception is None
            result = {"native_resizes": 3, "source_reused_on_geometry": True,
                      "style_selection_source_updates": True, "provider_inputs": 0}
            (tmp_path / "result.json").write_text(json.dumps(result) + "\n")
            print(json.dumps(result), flush=True)

    asyncio.run(mounted())
