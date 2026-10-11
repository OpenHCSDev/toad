"""Textual-facing: a selection drag cannot target a diff widget that was retired after the compositor's last hit map."""

from unittest.mock import patch

from textual import events
from textual.geometry import Offset
from textual.screen import Screen

from agent_comms.tool_results import ToolDiff, tool_result_content

from support.textual_steps import tool_status, wait_for_tool_diff
from toad.widgets.tool_call import ToolCall


async def test_drag_over_a_removed_diff_widget_is_ignored(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, pilot = ui.textual
        patch_text = "--- file.py\n+++ file.py\n@@ -1 +1 @@\n-old\n+new\n"
        tool = await ui.conversation.post(ToolCall(tool_status({
            "toolCallId": "edit", "title": "Edit file.py", "kind": "edit", "status": "completed",
            "content": tool_result_content("edit", "done", ToolDiff(patch_text))})))
        await wait_for_tool_diff(ui, tool)
        code = tool.query_one("DiffCode")
        await pilot.mouse_down(code, offset=(0, 0))
        x, y = code.region.x, code.region.y
        # Retire the selected node, but have the compositor return the
        # previous frame's hit until its next layout has committed.
        await code.remove()
        assert code.parent is None
        with patch.object(Screen, "get_widget_and_offset_at", return_value=(code, Offset(0, 0))):
            app.screen._forward_event(events.MouseMove(None, x, y, 0, 1, 1, False, False, False))
        await pilot.mouse_up(offset=(x, y))
        await ui.step()
