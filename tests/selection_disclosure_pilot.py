"""One purple selected row; user-expanded latest tools stay expanded."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar
from toad.widgets.session_sidebar import ThreadStatusRow
from toad.widgets.tool_call import ToolCall, ToolCallHeader, TextContent


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-selection-disclosure-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        for name in ("first", "second", "third"):
            comms.register(Thread(name, frozenset({"review"}), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 42)) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar._read_snapshot(comms.revision())
            group = next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#review")
            if not group.expanded:
                group.toggle_members()
            await pilot.pause()
            rows = {row.thread_name: row for row in group.query(ThreadStatusRow)}
            assert rows.keys() >= {"first", "second", "third"}
            # Selection denotes the remembered destination. Focus and hover
            # are navigation hints, never a second filled selection.
            sidebar.remember_row(rows["first"])
            rows["second"].focus(scroll_visible=False)
            await pilot.hover(rows["third"])
            await pilot.pause()
            assert sum(row.has_class("-selected") for row in sidebar._ordered_rows()) == 1
            assert rows["first"].has_class("-selected")
            assert rows["second"].has_focus
            assert "hover" in rows["third"].pseudo_classes
            purple = rows["first"].get_visual_style().background
            assert purple.ansi == 5, purple  # pywal-owned magenta, not fixed RGB
            assert rows["first"].get_visual_style().foreground.ansi == 0
            for name in ("second", "third"):
                background = rows[name].get_visual_style().background
                assert background != purple, (name, background)

            app.settings.set("tools.expand", "success")
            conversation = app.screen.conversation
            payload = {"sessionUpdate": "tool_call", "toolCallId": "last-tool", "title": "Run tests",
                       "status": "in_progress", "kind": "execute",
                       "content": [{"type": "content", "content": {"type": "text", "text": "Result"}}]}
            tool = await conversation.post(ToolCall(payload))
            await pilot.pause()
            assert not tool.expanded
            await pilot.click(tool.query_one(ToolCallHeader))
            await pilot.pause()
            assert tool.expanded and tool.query_one(TextContent).render().plain == "Result"
            for status in ("in_progress", "completed"):
                await tool.update_tool_call({**payload, "status": status})
                await pilot.pause()
                assert tool.expanded and tool.query_one(TextContent).render().plain == "Result"
            # Canonical model history can retire/remount the widget while the
            # output is the last thing in chat; that must keep explicit intent.
            await tool.remove()
            restored = await conversation.post(ToolCall({**payload, "status": "completed"}))
            await pilot.pause()
            assert restored.expanded and restored.query_one(TextContent)
            await pilot.click(restored.query_one(ToolCallHeader))
            await pilot.pause()
            assert not restored.expanded
            await restored.update_tool_call({**payload, "status": "completed"})
            await pilot.pause()
            assert not restored.expanded and not restored.query(TextContent)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("selection/disclosure: single purple highlight, unfilled focus/hover, stable manual tool state")


if __name__ == "__main__":
    asyncio.run(main())
