"""Installed native widget path: retained sessions construct panels on reveal."""

import asyncio
import gc
from importlib.resources import files
import json
import os
from pathlib import Path
import time
import shlex
from tempfile import TemporaryDirectory

import psutil

from runtime_fixture import ToadApp, stop_test_owners
from toad.acp import messages as acp_messages
from toad.screens.main import MainScreen
from toad.widgets.comms_sidebar import CoordinationStatus
from toad.widgets.plan import Plan
from toad.widgets.project_panel import ProjectPanel
from toad.widgets.side_bar import SideBar


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


async def main():
    with TemporaryDirectory(prefix="toad-panels-", dir=os.environ["TOAD_ARTIFACT_ROOT"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = InstalledApp(project_dir=str(root))
        measurements = []
        started = time.monotonic()
        try:
            async with app.run_test(headless=os.environ.get("TOAD_NATIVE") != "1", size=(120, 40)) as pilot:
                await pilot.pause()
                screens = []
                for index in range(int(os.environ.get("TOAD_PANEL_TABS", "16"))):
                    await app.new_session_screen(lambda: MainScreen(root, agent_session_id=f"retained-{index}"))
                    await pilot.pause(.02)
                    screen = app.screen
                    screens.append(screen)
                    sidebar = screen.query_one("#thread-sidebar", SideBar)
                    assert not sidebar.panels and not sidebar._panels_loaded
                    assert screen._project_panel is None
                    assert not screen.query(CoordinationStatus)
                    assert not screen.query(ProjectPanel)
                    if len(screens) in {4, 16, 32, 64}:
                        measurements.append({"tabs": len(screens), "rss_bytes": psutil.Process().memory_info().rss,
                                             "tasks": len(asyncio.all_tasks()), "tracked_objects": len(gc.get_objects()),
                                             "constructed_panels": sum(len(s.query_one("#thread-sidebar", SideBar).panels) for s in screens)})
                selected = screens[-1]
                conversation = selected.conversation
                editor = conversation.prompt.prompt_text_area
                editor.insert("retained draft")
                editor.history.checkpoint()
                editor.insert(" and undo")
                document, history, task = editor.document, editor.history, conversation._task
                project = root / "updated-project"
                project.mkdir()
                selected.project_path = project
                selected.on_comms_session_named("late-identity")
                sidebar = selected.query_one("#thread-sidebar", SideBar)
                await selected.on_acp_plan(acp_messages.Plan([
                    {"content": "Old plan", "priority": "low", "status": "pending"},
                ]))
                await selected.on_acp_plan(acp_messages.Plan([
                    {"content": "Latest plan", "priority": "high", "status": "in_progress"},
                ]))
                assert not sidebar.panels
                sidebar.reveal()
                sidebar.collapsed = True
                await pilot.pause()
                assert not sidebar.panels, "Cancelled reveal constructed hidden rich panels"
                sidebar.reveal()
                async with asyncio.timeout(8):
                    await sidebar.wait_content_ready()
                await pilot.pause()
                assert selected._project_panel.path == project
                assert sidebar.query_one(CoordinationStatus).thread == "late-identity"
                assert len(sidebar.query_one(Plan).entries) == 1
                assert sidebar.query_one(Plan).entries[0].content.plain == "Latest plan"
                widgets = tuple(panel.widget for panel in sidebar.panels)
                sidebar.collapsed = True
                await app.switch_mode(screens[0].id)
                await pilot.pause()
                assert conversation._task is task and not task.done()
                await app.switch_mode(selected.id)
                sidebar.reveal()
                await pilot.pause()
                assert tuple(panel.widget for panel in sidebar.panels) == widgets
                assert editor.document is document and editor.history is history
                assert editor.text == "retained draft and undo"
                editor.undo()
                assert editor.text == "retained draft"
                assert selected.conversation is conversation
                marker = root / "shell-still-operational"
                await conversation.post_shell("sleep 1; printf alive > " + shlex.quote(str(marker)))
                shell = conversation._shell
                await app.switch_mode(screens[0].id)
                async with asyncio.timeout(8):
                    while not marker.exists():
                        await pilot.pause(.05)
                assert marker.read_text() == "alive" and conversation._shell is shell
                await app.switch_mode(selected.id)
                assert editor.document is document and editor.history is history
                if os.environ.get("TOAD_NATIVE") == "1":
                    editor.focus()
                    await pilot.pause()
                    Path(os.environ["TOAD_NATIVE_READY"]).write_text("ready")
                    async with asyncio.timeout(8):
                        while "NATIVE" not in editor.text:
                            await pilot.pause(.02)
                assert app._exception is None
        finally:
            stop_test_owners(root / "wire")
        result = {"measurements": measurements, "elapsed_seconds": time.monotonic()-started,
                  "native_terminal": os.environ.get("TOAD_NATIVE") == "1",
                  "evidence": "mounted retained-session UI; unchanged conversation/editor; no provider ACP claimed"}
        Path(os.environ["TOAD_PANEL_RECEIPT"]).write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
