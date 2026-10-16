"""Textual-facing: a tool call's diff, prepared by the render worker processes, survives being hidden and shown, replaced, retheme'd, collapsed, remounted and removed."""

from agent_comms.tool_results import ToolDiff, tool_result_content
from textual.screen import Screen

from support.textual_steps import tool_status, wait_for_tool_diff
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import ToolContent

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
        assert tool.expanded and len(tool.query(ToolContent)) == 1
        await ui.until(lambda: not app._background_render_tasks, seconds=15, why="the render worker to finish")
        await app.pop_screen()
        await ui.step()
        first = await wait_for_tool_diff(ui, tool)
        assert ui.shows("new = 2")
        assert "old = 1" in first.get_clipboard_text() and "new = 2" in first.get_clipboard_text()


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
        assert current is first and current.is_attached
        assert ui.shows("fresh = 3") and not ui.shows("new = 2")
        for theme in ("ansi-light", "ansi-dark"):
            app.theme = theme
            await ui.step()
            await wait_for_tool_diff(ui, tool)
            assert ui.shows("fresh = 3")

        tool.collapse_block()
        await ui.step()
        assert not current.blocks
        tool.expand_block()
        current = await wait_for_tool_diff(ui, tool)
        assert ui.shows("fresh = 3")
        await tool.remove()
        await body.mount(tool)
        await wait_for_tool_diff(ui, tool)
        assert ui.shows("fresh = 3")
        await tool.remove()
        await ui.step()
        assert not current.is_attached
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
        assert auto.expanded and len(auto.query(ToolContent)) == 1
        await app.pop_screen()
        await wait_for_tool_diff(ui, auto)
        assert ui.shows("fresh = 3")
        await auto.remove()
        await ui.step()
        assert not app._background_render_tasks
