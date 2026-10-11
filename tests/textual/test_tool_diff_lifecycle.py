"""Textual-facing: a tool call's diff, prepared by the render worker processes, survives being hidden and shown, replaced, retheme'd, collapsed, remounted and removed."""

import gc
import warnings

from agent_comms.tool_results import ToolDiff, tool_result_content
from textual.screen import Screen

from support.textual_steps import tool_status, wait_for_tool_diff
from toad.widgets.patch_diff import PatchDiffView
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import ToolCallDiff

PATCH = "--- x.py\n+++ x.py\n@@ -1 +1 @@\n-old = 1\n+new = 2\n"


def edit_call(source=PATCH, *, tool_id="actual-output"):
    return tool_status({"toolCallId": tool_id, "title": "Actual edit x.py", "kind": "edit",
                        "status": "completed", "content": tool_result_content(tool_id, "done", ToolDiff(source))})


async def test_diff_is_prepared_while_hidden_and_shown_when_revealed(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        body = ui.conversation.contents
        await app.push_screen(Screen())
        tool = ToolCall(edit_call())
        await body.mount(tool)
        await ui.step()
        assert tool.expanded and not tool.query(ToolCallDiff), "Hidden warmup mounted UI"
        await ui.until(lambda: not app._background_render_tasks, seconds=15, why="the render worker to finish")
        await app.pop_screen()
        await ui.step()
        first = await wait_for_tool_diff(ui, tool)
        assert ui.shows("new = 2")
        assert first.query_one(PatchDiffView).counts == (1, 1)


async def test_diff_follows_replacement_theme_collapse_remount_and_removal(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        body = ui.conversation.contents
        tool = ToolCall(edit_call())
        await body.mount(tool)
        first = await wait_for_tool_diff(ui, tool)
        fresh = PATCH.replace("new = 2", "fresh = 3")
        await tool.update_tool_call(edit_call(fresh))
        current = await wait_for_tool_diff(ui, tool)
        assert current is not first and not first.is_attached and not first.prepared.is_set()
        assert ui.shows("fresh = 3") and not ui.shows("new = 2")
        for theme in ("ansi-light", "ansi-dark"):
            app.theme = theme
            await ui.step()
            await wait_for_tool_diff(ui, tool)
            assert ui.shows("fresh = 3")

        tool.collapse_block()
        await ui.step()
        assert not tool.query(ToolCallDiff) and not current.prepared.is_set()
        tool.expand_block()
        current = await wait_for_tool_diff(ui, tool)
        assert ui.shows("fresh = 3")
        await current.remove()
        await tool.query_one("#tool-content").mount(current)
        await wait_for_tool_diff(ui, tool)
        assert ui.shows("fresh = 3")
        await tool.remove()
        await ui.step()
        assert not current.is_attached and not current.prepared.is_set()
        assert not ui.shows("fresh = 3")


async def test_remounting_an_auto_expanded_tool_while_hidden_registers_its_output_again(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        body = ui.conversation.contents
        fresh = PATCH.replace("new = 2", "fresh = 3")
        auto = ToolCall(edit_call(fresh, tool_id="auto-output"))
        await body.mount(auto)
        await wait_for_tool_diff(ui, auto)
        await auto.remove()
        await app.push_screen(Screen())
        await body.mount(auto)
        await ui.step()
        assert auto.expanded and not auto.query(ToolCallDiff)
        # Worker cancellation before entry: scheduling creates no coroutine,
        # and a stale warmup cannot publish.
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", RuntimeWarning)
            auto.output.cancel_preparation()
            auto.output.prepare_hidden()
            auto.output.cancel_preparation()
            worker = auto.run_worker(auto.output.hydrate, group="visible-content")
            worker.cancel()
            await ui.step()
            gc.collect()
            assert not any("was never awaited" in str(item.message) for item in observed), observed
        await app.pop_screen()
        await wait_for_tool_diff(ui, auto)
        assert ui.shows("fresh = 3")
        await auto.remove()
        await ui.step()
        assert not app._background_render_tasks
