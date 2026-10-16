"""Textual-facing: an auto-expanded tool call keeps one leaf and paints its rows when scrolled into view."""

from agent_comms.tool_results import ToolDiff, tool_result_content

from support.textual_steps import tool_status, wait_for_tool_diff
from toad.setting_choices import AlwaysExpansion
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import ToolContent
from toad.preferences import SETTINGS

PATCH = "--- first.py\n+++ first.py\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n"


async def test_diff_of_an_offscreen_auto_expanded_tool_mounts_when_scrolled_into_view(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        app, _ = ui.textual
        app.saved_settings.set(SETTINGS.tools.expand, AlwaysExpansion)
        tools = [ToolCall(tool_status({
            "toolCallId": f"edit-{index}", "title": f"Edit file {index}", "kind": "edit", "status": "completed",
            "content": tool_result_content(f"edit-{index}", "done", ToolDiff(PATCH))})) for index in range(28)]
        await ui.conversation.contents.mount(*tools)
        ui.conversation.window.anchor()
        await ui.step()
        first, last = tools[0], tools[-1]
        assert first.expanded and len(first.query(ToolContent)) == 1
        last.scroll_visible(animate=False)
        await ui.step()
        assert "new" in (await wait_for_tool_diff(ui, last)).get_clipboard_text()
        first.scroll_visible(animate=False)
        await ui.step()
        assert "new" in (await wait_for_tool_diff(ui, first)).get_clipboard_text()
