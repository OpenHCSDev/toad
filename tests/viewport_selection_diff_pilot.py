"""Viewport selection across a clipped native diff matches Textual's full walker."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms.tool_results import ToolDiff, tool_result_content
from runtime_fixture import ToadApp
from tool_diff_fixture import wait_for_tool_diff
from textual import events
from textual.selection import SELECT_ALL, SelectState

from toad.widgets.agent_response import AgentResponse
from toad.widgets.tool_call import ToolCall, ToolCallDiff


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-select-diff-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            app.settings.set("ui.auto_copy", False)
            source = await app.screen.conversation.post(AgentResponse("START marker\n\nBefore the diff."))
            text = "very_long_identifier_" * 9
            patch_text = ("--- x.py\n+++ x.py\n@@ -1,2 +1,2 @@\n context\n"
                          f"-{text}\n+{text} updated\n")
            tool = await app.screen.conversation.post(ToolCall({"toolCallId": "edit", "title": "Edit x.py",
                "kind": "edit", "status": "completed",
                "content": tool_result_content("edit", "done", ToolDiff(patch_text))}))
            destination = await app.screen.conversation.post(AgentResponse("After the diff.\n\nEND marker"))
            await pilot.pause()
            await wait_for_tool_diff(tool, pilot)
            assert tool.query_one(ToolCallDiff)
            start = source.query_one("MarkdownParagraph")
            end = destination.query_one("MarkdownParagraph")
            code = tool.query_one("DiffCode")
            assert code.is_mounted and code in app.screen._compositor.visible_widgets
            viewport = app.screen.conversation.window.content_region
            assert viewport.contains_point(start.region.offset)
            assert viewport.contains_point(end.region.offset)
            screen = app.screen
            x1, y1 = start.region.x, start.region.y
            x2, y2 = end.region.x + len("After the diff."), end.region.y
            screen._forward_event(events.MouseDown(None, x1, y1, 0, 0, 1, False, False, False))
            screen._forward_event(events.MouseMove(None, x2, y2, x2 - x1, y2 - y1,
                                                  1, False, False, False))
            screen._stop_auto_scroll()
            await pilot.pause()
            state = screen._select_state
            assert state is not None and state.end is not None
            clipped = [widget for widget in screen._compositor.visible_widgets
                       if widget.is_scrollable and widget.max_scroll_x > 0
                       and state.selection_bounds.overlaps(widget.region)]
            assert clipped, "Fixture did not cross a horizontally clipped result"
            fast = state._walk_viewport_widgets()
            assert fast is None, "Clipped diff must retain the complete native selection walker"
            with patch.object(SelectState, "_walk_viewport_widgets", return_value=None):
                original = state._walk_selected_widgets()
            native_selections = dict.fromkeys(original, SELECT_ALL)
            state._apply_content_selections(native_selections)
            native_text = "".join(
                piece for widget, selection in native_selections.items() if widget.is_attached
                for piece in (widget.get_selection(selection) or ())
            ).rstrip("\n")
            # The diff has several asynchronously mounted code/annotation
            # widgets. A later pointer move updates selection after their
            # committed layout, just as a real continuous drag does.
            screen._update_select()
            await pilot.pause()
            selected = screen.get_selected_text()
            assert selected == native_text, (repr(selected), repr(native_text))
            assert "START marker" in selected and "After the diff." in selected and text in selected
            screen._forward_event(events.MouseUp(None, x2, y2, 0, 0, 1, False, False, False))
        await asyncio.get_running_loop().shutdown_default_executor()
    print("native selection: clipped diff and surrounding messages retain full copy order")


if __name__ == "__main__":
    asyncio.run(main())
