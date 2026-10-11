"""Textual-facing: dragging a selection across a horizontally clipped diff copies the same text as Textual's full selection walker."""

from unittest.mock import patch

from agent_comms.tool_results import ToolDiff, tool_result_content
from textual import events
from textual.selection import SELECT_ALL, SelectState

from support.textual_steps import tool_status, wait_for_tool_diff
from toad.widgets.agent_response import AgentResponse
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import ToolCallDiff


async def test_drag_across_clipped_diff_matches_the_full_walker(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        app, _ = ui.textual
        app.settings.ui.auto_copy = False
        conversation = ui.conversation
        source = await conversation.post(AgentResponse("START marker\n\nBefore the diff."))
        text = "very_long_identifier_" * 9
        patch_text = ("--- x.py\n+++ x.py\n@@ -1,2 +1,2 @@\n context\n"
                      f"-{text}\n+{text} updated\n")
        tool = await conversation.post(ToolCall(tool_status({
            "toolCallId": "edit", "title": "Edit x.py", "kind": "edit", "status": "completed",
            "content": tool_result_content("edit", "done", ToolDiff(patch_text))})))
        destination = await conversation.post(AgentResponse("After the diff.\n\nEND marker"))
        await ui.step()
        await wait_for_tool_diff(ui, tool)
        assert tool.query_one(ToolCallDiff)
        code = tool.query_one("DiffCode")
        assert code.is_mounted and code in app.screen._compositor.visible_widgets
        viewport = conversation.window.content_region
        assert viewport.contains_point(source.body.region.offset)
        assert viewport.contains_point(destination.body.region.offset)
        screen = app.screen
        x1, y1 = source.body.region.x, source.body.region.y
        x2, y2 = destination.body.region.x + len("After the diff."), destination.body.region.y
        screen._forward_event(events.MouseDown(None, x1, y1, 0, 0, 1, False, False, False))
        screen._forward_event(events.MouseMove(None, x2, y2, x2 - x1, y2 - y1, 1, False, False, False))
        screen._stop_auto_scroll()
        await ui.step()
        state = screen._select_state
        assert state is not None and state.end is not None
        clipped = [widget for widget in screen._compositor.visible_widgets
                   if widget.is_scrollable and widget.max_scroll_x > 0
                   and state.selection_bounds.overlaps(widget.region)]
        assert clipped, "Fixture did not cross a horizontally clipped result"
        assert state._walk_viewport_widgets() is None, "Clipped diff must retain the complete native selection walker"
        with patch.object(SelectState, "_walk_viewport_widgets", return_value=None):
            walked = state._walk_selected_widgets()
        native_selections = dict.fromkeys(walked, SELECT_ALL)
        state._apply_content_selections(native_selections)
        native_text = "".join(
            piece for widget, selection in native_selections.items() if widget.is_attached
            for piece in (widget.get_selection(selection) or ())
        ).rstrip("\n")
        # A later pointer move updates the selection after the asynchronously
        # mounted diff widgets have their committed layout, as a real drag does.
        screen._update_select()
        await ui.step()
        selected = screen.get_selected_text()
        assert selected == native_text, (repr(selected), repr(native_text))
        assert "START marker" in selected and "After the diff." in selected and text in selected
        screen._forward_event(events.MouseUp(None, x2, y2, 0, 0, 1, False, False, False))
