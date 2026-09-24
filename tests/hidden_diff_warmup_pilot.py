"""Hidden open views prepare diff data before activation; stale work stays bounded."""

import asyncio
import os
from pathlib import Path
import tempfile
from typing import TypeVar, cast

from agent_comms.tool_results import ToolDiff, tool_result_content
from runtime_fixture import ToadApp
from tool_diff_fixture import wait_for_tool_diff
from toad.render_backend import Renderer
from toad.render_tasks import PatchRenderTask, RenderTask
from toad.widgets.tool_call import ToolCall, ToolCallDiff
from toad.widgets.patch_diff import PreparedPatch

ResultT = TypeVar("ResultT")
PATCH = "--- x.py\n+++ x.py\n@@ -1 +1 @@\n-old = 1\n+new = 2\n"


class ControlledRenderer(Renderer):
    def __init__(self):
        self.requests: list[tuple[PatchRenderTask, asyncio.Future[PreparedPatch]]] = []

    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        assert isinstance(task, PatchRenderTask)
        future: asyncio.Future[PreparedPatch] = asyncio.get_running_loop().create_future()
        self.requests.append((task, future))
        await asyncio.wait((future,))
        return cast(ResultT, future.result())

    def complete(self, index: int) -> None:
        task, future = self.requests[index]
        if not future.done():
            future.set_result(task.execute())

    async def aclose(self) -> None:
        for index in range(len(self.requests)):
            self.complete(index)


def data(name, source=PATCH):
    return {"toolCallId": name, "title": "Edit x.py", "kind": "edit", "status": "completed",
            "content": tool_result_content(name, "Done", ToolDiff(source))}


async def until(pilot, condition):
    async with asyncio.timeout(5):
        while not condition():
            await pilot.pause(.01)


async def main():
    with tempfile.TemporaryDirectory(prefix="hidden-diff-warmup-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        renderer = ControlledRenderer()
        app = ToadApp(project_dir=directory, renderer=renderer)
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            owner, screen = app.current_mode, app.screen
            await app.switch_mode("store")
            tool = await screen.conversation.post(ToolCall(data("warm")))
            await until(pilot, lambda: len(renderer.requests) == 1)
            assert not tool.query(ToolCallDiff), "Hidden preparation mounted rich UI"
            renderer.complete(0)
            await until(pilot, lambda: tool._warm_patches[PATCH].result.done())
            await app.switch_mode(owner)
            tool.scroll_visible(animate=False)
            result = await wait_for_tool_diff(tool, pilot)
            assert result.patch == PATCH and len(renderer.requests) == 1
            await tool.remove()

            await app.switch_mode("store")
            stale = await screen.conversation.post(ToolCall(data("stale")))
            await until(pilot, lambda: len(renderer.requests) == 2)
            replacement = PATCH.replace("new = 2", "fresh = 3")
            await stale.update_tool_call(data("stale", replacement))
            await pilot.pause()
            assert len(renderer.requests) == 2, "Cancellation released background CPU admission early"
            renderer.complete(1)
            await until(pilot, lambda: len(renderer.requests) == 3)
            renderer.complete(2)
            await until(pilot, lambda: stale._warm_patches[replacement].result.done())
            assert PATCH not in stale._warm_patches
            app.theme = "ansi-light"
            await until(pilot, lambda: len(renderer.requests) == 4)
            assert renderer.requests[3][0].ansi and not renderer.requests[3][0].dark
            renderer.complete(3)
            await until(pilot, lambda: stale._warm_patches[replacement].result.done())
            await app.switch_mode(owner)
            stale.scroll_visible(animate=False)
            result = await wait_for_tool_diff(stale, pilot)
            assert result.patch == replacement and len(renderer.requests) == 4
            assert app._exception is None
        assert not app._background_render_tasks
        await asyncio.get_running_loop().shutdown_default_executor()
    print("hidden diffs: prepared before activation, no duplicate submit, stale generations discarded, admission retained")


if __name__ == "__main__":
    asyncio.run(main())
