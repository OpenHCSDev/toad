"""One multi-select semantic filter governs live blocks and saved transcript."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms import (
    Message, MessageRoute, MessageType, Thread, TranscriptCursor, TranscriptEvent,
    TranscriptPage, TurnRouting, wire,
)
from textual.widgets import Checkbox

from runtime_fixture import ToadApp
from toad.acp.messages import CoordinationUpdate
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.message_filter import ALL_CATEGORIES, MESSAGE_CATEGORIES, MessageCategory
from toad.widgets.note import Note
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.thread_comms import ThreadCommsSidebar
from toad.widgets.tool_call import ToolCall
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.user_input import UserInput


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-message-categories-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        for name in ("owner", "peer"):
            comms.register(Thread(name, frozenset(), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(130, 43)) as pilot:
            await pilot.pause()
            screen = app.screen
            await screen.on_coordination_update(CoordinationUpdate(
                thread="owner", wire_root=str(root / "wire"), persistence="persistent", transport="stdio"))
            sidebar = screen.query_one("#thread-sidebar", SideBar)
            sidebar.reveal()
            filters = screen.query_one(ThreadCommsSidebar)
            filters.query_ancestor(SideBarCollapsible).collapsed = False
            await pilot.pause()
            choices = {category: filters.query_one(f"#filter-{category.value}", Checkbox)
                       for category in MESSAGE_CATEGORIES}
            assert all(checkbox.display and checkbox.value for checkbox in choices.values())

            view = screen.conversation
            view.prompt.text = "keep draft"
            live = {
                MessageCategory.USER: UserInput("user"),
                MessageCategory.AGENT: AgentResponse("agent"),
                MessageCategory.INBOUND: IncomingMessage("peer", "incoming", "owner"),
                MessageCategory.OUTBOUND: AgentResponse("outgoing", route=MessageRoute("owner", ("peer",))),
                MessageCategory.THINKING: AgentThought("thinking"),
                MessageCategory.TOOL: ToolCall({"toolCallId": "filter-tool", "kind": "execute",
                                                "title": "tool", "status": "completed"}),
                MessageCategory.OTHER: Note("harness notice"),
            }
            await view.contents.mount(*live.values())

            message = Message("peer", "owner", "IN", MessageType.INFO)
            saved = (
                TranscriptEvent("user", "SAVED_USER"),
                TranscriptEvent("assistant", "SAVED_AGENT"),
                TranscriptEvent("user", "SAVED_IN", routing=TurnRouting((message,), None)),
                TranscriptEvent("sent", "SAVED_OUT", routing=TurnRouting(
                    (), MessageRoute("owner", ("peer",)))),
                TranscriptEvent("thinking", "SAVED_THINKING"),
                TranscriptEvent("tool_start", "SAVED_TOOL", tool_call_id="t", tool_name="read"),
                TranscriptEvent("tool_end", "SAVED_TOOL_DONE", tool_call_id="t", tool_name="read"),
                TranscriptEvent("notice", "SAVED_NOTICE"),
            )
            cursor = TranscriptCursor("fixture", 0)
            history = TranscriptHistory(TranscriptPage(saved, cursor, cursor, False, False))
            await view.contents.mount(history)
            await pilot.pause()
            fragments = {leaf._message_category: leaf for leaf in history.pages[0].children}
            assert set(fragments) == set(MESSAGE_CATEGORIES)
            assert all(widget.message_category == kind for kind, widget in live.items() if kind != MessageCategory.OTHER)

            for category in MESSAGE_CATEGORIES:
                view.visible_categories = frozenset((category,))
                await pilot.pause()
                assert all(widget.display == (kind == category) for kind, widget in live.items()), category
                assert all(leaf.display == (kind == category) for kind, leaf in fragments.items()), category
                assert history.display and view.prompt.text == "keep draft"
                with patch.object(app.coordination_wire, "mark_thread_view_read") as mark:
                    view.displayed_transcript_cursor = cursor
                    await app.mark_visible_thread_read()
                    mark.assert_not_called()

            # The sidebar updates a single category without replacing other
            # choices; the selection belongs only to this conversation tab.
            assert await pilot.click(choices[MessageCategory.USER])
            await pilot.pause()
            assert view.visible_categories == frozenset((MessageCategory.OTHER, MessageCategory.USER))
            other_mode = (await app.new_session_screen(app.get_main_screen)).mode_name
            assert app.screen.conversation.visible_categories == ALL_CATEGORIES
            await app.switch_mode(screen.id)
            await pilot.pause()
            assert view.visible_categories == frozenset((MessageCategory.OTHER, MessageCategory.USER))
            assert view.prompt.text == "keep draft"
            view.visible_categories = ALL_CATEGORIES
            await pilot.pause()
            assert all(block.display for block in live.values())
            assert all(leaf.display for leaf in fragments.values())
            assert view.prompt.text == "keep draft" and other_mode in app._open_tab_order
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("seven categories: polymorphic live blocks, saved fragments, multi-select UI, per-tab state, draft and read boundary OK")


if __name__ == "__main__":
    asyncio.run(main())
