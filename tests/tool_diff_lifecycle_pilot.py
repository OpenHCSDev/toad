"""Actual installed render workers survive hide/show, replacement and retirement."""

import asyncio
from importlib.resources import files
import os
from pathlib import Path
import tempfile

from agent_comms.tool_results import ToolDiff, tool_result_content
from runtime_fixture import ToadApp
from tool_diff_fixture import wait_for_tool_diff
from textual.screen import Screen
from toad.widgets.patch_diff import PatchDiffView
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import ToolCallDiff

PATCH = "--- x.py\n+++ x.py\n@@ -1 +1 @@\n-old = 1\n+new = 2\n"


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


def data(source=PATCH):
    return {"toolCallId": "actual-output", "title": "Actual edit x.py", "kind": "edit",
            "status": "completed", "content": tool_result_content("actual-output", "done", ToolDiff(source))}


def frame(app):
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-output-life-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = InstalledApp(project_dir=directory)
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            body = app.screen.conversation.contents
            await app.push_screen(Screen())
            tool = ToolCall(data())
            await body.mount(tool)
            await pilot.pause()
            assert tool.expanded and not tool.query(ToolCallDiff), "Hidden warmup mounted UI"
            # Real App admission remains owned while the renderer process runs.
            async with asyncio.timeout(15):
                while app._background_render_tasks:
                    await pilot.pause(.02)
            await app.pop_screen()
            await pilot.pause()
            first = await wait_for_tool_diff(tool, pilot)
            assert "new = 2" in frame(app)
            assert first.query_one(PatchDiffView).counts == (1, 1)

            fresh = PATCH.replace("new = 2", "fresh = 3")
            await tool.update_tool_call(data(fresh))
            current = await wait_for_tool_diff(tool, pilot)
            assert current is not first and not first.is_attached and not first.prepared.is_set()
            assert "fresh = 3" in frame(app) and "new = 2" not in frame(app)
            for theme in ("ansi-light", "ansi-dark"):
                app.theme = theme
                await pilot.pause()
                await wait_for_tool_diff(tool, pilot)
                assert "fresh = 3" in frame(app)

            tool.collapse_block()
            await pilot.pause()
            assert not tool.query(ToolCallDiff) and not current.prepared.is_set()
            tool.expand_block()
            current = await wait_for_tool_diff(tool, pilot)
            assert "fresh = 3" in frame(app)
            await current.remove()
            await tool.query_one("#tool-content").mount(current)
            await wait_for_tool_diff(tool, pilot)
            assert "fresh = 3" in frame(app)
            await tool.remove()
            await pilot.pause()
            assert not current.is_attached and not current.prepared.is_set()
            assert "fresh = 3" not in frame(app)
            assert not app._background_render_tasks and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("REAL_RENDERER: hidden preparation/reveal, replacement, theme, collapse/reopen, remount/retirement and actual paint")


if __name__ == "__main__":
    asyncio.run(main())
