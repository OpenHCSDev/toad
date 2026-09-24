"""Live and replayed native edit patches render identically without eager large diffs."""

import asyncio
import os
import tempfile
from pathlib import Path
from rich.syntax import Syntax
from textual.content import Content
from textual.selection import SELECT_ALL

from agent_comms import TranscriptEvent
from agent_comms.tool_results import ToolDiff, tool_result_content
from runtime_fixture import ToadApp
from tool_diff_fixture import wait_for_tool_diff
from toad.widgets.tool_call import ToolCall, ToolCallDiff
from toad.widgets.patch_diff import PatchDiffView, parse_patch
from toad.widgets.transcript_history import transcript_blocks


PATCH = "--- src/example.py\n+++ src/example.py\n@@ -40,2 +40,2 @@\n context\n-old = 1\n+new = 2\n"


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-tool-diff-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            content = tool_result_content("edit-1", "Successfully replaced 1 block.", ToolDiff(PATCH))
            live = await conversation.post(ToolCall({"toolCallId": "edit-1", "title": "Edit src/example.py",
                "kind": "edit", "status": "in_progress"}))
            assert not live.expanded
            await live.update_tool_call({"toolCallId": "edit-1", "title": "Edit src/example.py",
                "kind": "edit", "status": "completed", "content": content})
            await pilot.pause()
            assert live.expanded and live.query_one(ToolCallDiff).patch == PATCH
            await wait_for_tool_diff(live, pilot)
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "old = 1" in frame and "new = 2" in frame and "@@ -40,2 +40,2 @@" not in frame
            diff = live.query_one(ToolCallDiff)
            rich_diff = diff.query_one(PatchDiffView)
            assert rich_diff.counts == (1, 1)
            assert rich_diff.grouped_opcodes[0][-1] == ("replace", 40, 41, 40, 41)
            rich_diff.split = True
            await pilot.pause()
            assert len(rich_diff.query("DiffCode")) == 2
            await live.remove()
            replay = transcript_blocks((TranscriptEvent("tool_end", "Successfully replaced 1 block.",
                tool_call_id="edit-1", tool_name="edit", diff=ToolDiff(PATCH)),))[0]
            await conversation.post(replay)
            await pilot.pause()
            replay.scroll_visible(animate=False)
            await pilot.pause()
            await wait_for_tool_diff(replay, pilot)
            assert replay.expanded and replay.query_one(ToolCallDiff).patch == PATCH
            replay.collapse_block()
            await pilot.pause()
            assert not replay.query(ToolCallDiff)
            replay.expand_block()
            await pilot.pause()
            await wait_for_tool_diff(replay, pilot)
            assert replay.query_one(ToolCallDiff).patch == PATCH
            # Keep large patches lazy but retain every line when explicitly opened.
            huge = PATCH.replace("-40,2 +40,2", "-40,302 +40,302") + " context\n" * 300
            large = await conversation.post(ToolCall({"toolCallId": "large", "title": "Large edit",
                "status": "completed", "content": tool_result_content("large", "done", ToolDiff(huge))}))
            await pilot.pause()
            assert not large.expanded and not large.query(ToolCallDiff)
            large.expand_block()
            await pilot.pause()
            await wait_for_tool_diff(large, pilot)
            assert large.query_one(ToolCallDiff).patch == huge
            # High source offsets are represented sparsely, not by allocating
            # a fake file prefix just to make the line numbers look right.
            distant = PATCH.replace("-40,2 +40,2", "-1000000,2 +1000000,2")
            sparse = await conversation.post(PatchDiffView(parse_patch(distant), split=False))
            await pilot.pause()
            before, after = sparse.highlighted_code_lines
            assert len(before.positions) == len(after.positions) == 2
            assert sparse.counts == (1, 1)
            blank_tail = PATCH.replace("-40,2 +40,2", "-830,4 +830,4") + " \n \n"
            blanks = await conversation.post(PatchDiffView(parse_patch(blank_tail), split=False))
            await pilot.pause()
            before, after = blanks.highlighted_code_lines
            assert [line.plain for line in before[829:833]] == ["context", "old = 1", "", ""]
            assert [line.plain for line in after[829:833]] == ["context", "new = 2", "", ""]
            blanks.split = True
            await pilot.pause()
            assert app._exception is None
            # Read output uses syntax colors and remains selectable as exact text.
            from toad.widgets.tool_call import TextContent
            from toad.widgets.worker_static import WorkerStatic
            code = "def example(value):\n    return value + 1\n"
            read = ToolCall({"toolCallId": "read", "title": "Read example.py", "kind": "read",
                "status": "completed", "rawInput": {"path": "example.py"},
                "content": [{"type": "content", "content": {"type": "text", "text": code}}]})
            read.expanded = True
            await conversation.post(read)
            await pilot.pause()
            worker_content = read.query_one(WorkerStatic)
            await asyncio.wait_for(worker_content.wait_ready(), 15)
            assert worker_content._prepared is not None
            assert worker_content.get_selection(SELECT_ALL)[0] == SELECT_ALL.extract(code)
            app.theme = "ansi-light"
            await pilot.pause()
            await asyncio.wait_for(worker_content.wait_ready(), 15)
            assert worker_content._ready_request.task.presentation.dark is app.current_theme.dark
            assert worker_content.get_selection(SELECT_ALL)[0] == SELECT_ALL.extract(code)

            malformed = "-removed\n+added\n"
            invalid = await conversation.post(ToolCall({"toolCallId": "invalid", "title": "Unparsed patch",
                "kind": "edit", "status": "completed",
                "content": tool_result_content("invalid", "done", ToolDiff(malformed))}))
            invalid.set_expanded(True)
            for theme in ("ansi-dark", "ansi-light"):
                app.theme = theme
                await pilot.pause()
                fallback = await wait_for_tool_diff(invalid, pilot)
                actual = fallback.query_one(TextContent).render()
                native = Content.from_rich_text(Syntax(
                    malformed, "diff", theme="ansi_dark", background_color="default"
                ).highlight(malformed))
                assert actual.plain == malformed and actual.spans == native.spans
    print("tool diffs: colored native patch live/replay, preserved hunk positions, bounded auto-expansion")


if __name__ == "__main__":
    asyncio.run(main())
