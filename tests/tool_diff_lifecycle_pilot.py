"""Late diff work never publishes into a replaced/collapsed view or stale theme."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms.tool_results import ToolDiff, tool_result_content
from runtime_fixture import ToadApp
from tool_diff_fixture import wait_for_tool_diff
from toad.widgets.patch_diff import PatchDiffView
from toad.render_tasks import execute_render_task
from toad.render_backend import Renderer
from toad.widgets.tool_call import ToolCall, ToolCallDiff

PATCH = "--- x.py\n+++ x.py\n@@ -1,2 +1,2 @@\n context\n-old = 1\n+new = 2\n"


class ControlledPool(Renderer):
    def __init__(self):
        self.requests = []

    async def run(self, function, *args):
        future = asyncio.get_running_loop().create_future()
        self.requests.append((function, args, future))
        await asyncio.wait((future,))
        return future.result()

    async def submit(self, task):
        return await self.run(execute_render_task, task)

    def complete(self, index):
        function, args, future = self.requests[index]
        assert function is execute_render_task
        future.set_result(function(*args))

    async def aclose(self):
        pass


async def requested(pool, count, pilot):
    async with asyncio.timeout(5):
        while len(pool.requests) < count:
            await pilot.pause()


def tool_data(tool_id, source=PATCH):
    return {"toolCallId": tool_id, "title": "Edit x.py", "kind": "edit", "status": "completed",
            "content": tool_result_content(tool_id, "Done", ToolDiff(source))}


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-diff-lifecycle-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        pool = ControlledPool()
        with patch.object(app, "render_processes", pool):
            async with app.run_test(size=(110, 35)) as pilot:
                await pilot.pause()
                owner = app.current_mode
                tool = ToolCall(tool_data("lifecycle"))
                tool.set_expanded(True)
                await app.screen.conversation.post(tool)
                await requested(pool, 1, pilot)
                first = tool.query_one(ToolCallDiff)
                app.theme = "ansi-light"
                await requested(pool, 2, pilot)
                pool.complete(0)
                await pilot.pause()
                assert not first.prepared.is_set() and not first.query(PatchDiffView)
                pool.complete(1)
                await wait_for_tool_diff(tool, pilot)
                assert first._prepared_patch.theme == (True, False)

                await tool.update_tool_call(tool_data("lifecycle", PATCH.replace("new = 2", "fresh = 3")))
                await requested(pool, 3, pilot)
                replaced = tool.query_one(ToolCallDiff)
                assert replaced is not first and not first.is_attached
                tool.collapse_block()
                await pilot.pause()
                pool.complete(2)
                await pilot.pause()
                assert not tool.query(ToolCallDiff) and not replaced.prepared.is_set()
                tool.expand_block()
                await requested(pool, 4, pilot)
                pool.complete(3)
                current = await wait_for_tool_diff(tool, pilot)
                assert "fresh = 3" in current.patch

                # A real instance removed/remounted must restart canceled state.
                body = tool.query_one("#tool-content")
                await current.remove()
                await body.mount(current)
                await requested(pool, 5, pilot)
                pool.complete(4)
                await wait_for_tool_diff(tool, pilot)
                await tool.remove()

                auto = await app.screen.conversation.post(ToolCall(tool_data("auto")))
                auto.scroll_visible(animate=False)
                await requested(pool, 6, pilot)
                async with asyncio.timeout(5):
                    while not auto.query(ToolCallDiff):
                        await pilot.pause()
                pending = auto.query_one(ToolCallDiff)
                await app.switch_mode("store")
                await pilot.pause()
                pool.complete(5)
                await pilot.pause()
                assert pending._prepared_patch is not None
                assert not pending.prepared.is_set() and not pending.query(PatchDiffView)
                await app.switch_mode(owner)
                auto.scroll_visible(animate=False)
                await wait_for_tool_diff(auto, pilot)
                assert pending._visibility_signal is None
                assert app._exception is None
    print("tool diff lifecycle: theme supersession, replacement, collapse, remount and hidden-tab delivery")


if __name__ == "__main__":
    asyncio.run(main())
