"""Textual-facing: an auto-expanded tool call mounts its diff only once its header is visible in the scrolled window."""

from agent_comms.tool_results import ToolDiff, tool_result_content

from support.textual_steps import tool_status, wait_for_tool_diff
from toad.setting_choices import AlwaysExpansion
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import ToolCallDiff

PATCH = "--- first.py\n+++ first.py\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n"


async def test_diff_of_an_offscreen_auto_expanded_tool_mounts_when_scrolled_into_view(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        app, _ = ui.textual
        app.settings.tools.expand = AlwaysExpansion
        tools = [ToolCall(tool_status({
            "toolCallId": f"edit-{index}", "title": f"Edit file {index}", "kind": "edit", "status": "completed",
            "content": tool_result_content(f"edit-{index}", "done", ToolDiff(PATCH))})) for index in range(28)]
        await ui.conversation.contents.mount(*tools)
        ui.conversation.window.anchor()
        await ui.step()
        first, last = tools[0], tools[-1]
        mounted = sum(bool(tool.query(ToolCallDiff)) for tool in tools)
        assert first.expanded and not first.query(ToolCallDiff)
        assert mounted < len(tools) // 2
        last.scroll_visible(animate=False)
        await ui.step()
        assert (await wait_for_tool_diff(ui, last)).patch == PATCH
        first.scroll_visible(animate=False)
        await ui.step()
        assert (await wait_for_tool_diff(ui, first)).patch == PATCH
