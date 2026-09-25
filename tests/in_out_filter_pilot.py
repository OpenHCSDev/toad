"""Native thread in/out filtering preserves routed bodies and reversible history."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms import (
    Message, MessageRoute, MessageType, Thread, TranscriptCursor, TranscriptEvent,
    TranscriptPage, TurnRouting, wire,
)
from textual.widgets import Checkbox, Static

from runtime_fixture import ToadApp
from toad.acp.messages import CoordinationUpdate
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar
from toad.widgets.message_filter import IN_OUT_CATEGORIES, MESSAGE_CATEGORIES, MessageCategory
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.user_input import UserInput


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-in-out-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        for name in ("owner", "peer"):
            comms.register(Thread(name, frozenset({"team"}), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(130, 44)) as pilot:
            await pilot.pause()
            owner_mode = app.current_mode
            screen = app.screen
            await screen.on_coordination_update(CoordinationUpdate(
                thread="owner", wire_root=str(root / "wire"), persistence="persistent", transport="stdio"))
            screen.query_one("#thread-sidebar", SideBar).reveal()
            tree = screen.query_one(ThreadCommsSidebar)
            panel = tree.query_ancestor(SideBarCollapsible)
            panel.collapsed = False
            await pilot.pause()
            async with asyncio.timeout(5):
                while tree._snapshot is None:
                    await pilot.pause(.02)
            checkboxes = {category: tree.query_one(f"#filter-{category.value}", Checkbox)
                          for category in MESSAGE_CATEGORIES}
            assert all(checkbox.display and checkbox.value for checkbox in checkboxes.values())
            owner_label = tree.query_one(".relationship-context", Static).render()
            assert any("bold" in str(span.style) for span in owner_label.spans)
            sort = panel.query_one(RelationshipSort)
            assert sort.region.y == panel.query_one("CollapsibleTitle").region.y
            assert not tree.query(RelationshipSort), "Sort remained inside a relationship group"

            view = screen.conversation
            view.prompt.text = "Unsent draft survives filtering"
            incoming = IncomingMessage("peer", "INCOMING_BODY", "owner")
            outgoing = AgentResponse("OUTGOING_BODY", route=MessageRoute("owner", ("peer",)))
            thought = AgentThought("PRIVATE_THOUGHT")
            plain = AgentResponse("Plain answer containing [FROM] and [TO] is not routed")
            request = UserInput("Ordinary user prompt")
            await view.contents.mount(request, thought, plain, incoming, outgoing)
            long_output = AgentResponse(route=MessageRoute("owner", ("#team",)))
            await view.contents.mount(long_output)
            await long_output.update("\n\n".join(f"ROUTED_PARAGRAPH_{i}" for i in range(100)))
            await pilot.pause()
            assert long_output._paged is not None

            message = Message("peer", "owner", "SAVED_INCOMING", MessageType.INFO)
            events = (
                TranscriptEvent("user", message.body, routing=TurnRouting((message,), None)),
                TranscriptEvent("thinking", "SAVED_THOUGHT"),
                TranscriptEvent("assistant", "SAVED_UNROUTED"),
                TranscriptEvent("sent", "SAVED_OUTGOING", routing=TurnRouting(
                    (), MessageRoute("owner", ("peer",)))),
            )
            cursor = TranscriptCursor("fixture", 0)
            history = TranscriptHistory(TranscriptPage(events, cursor, cursor, False, False))
            await view.contents.mount(history)
            await pilot.pause()
            leaves = list(history.pages[0].children)
            assert len(leaves) == 4
            view.window.release_anchor()
            view.window.scroll_to(y=min(7, view.window.max_scroll_y), animate=False, immediate=True)
            await pilot.pause()
            full_scroll = view.window.scroll_y
            for category in MESSAGE_CATEGORIES:
                if category not in IN_OUT_CATEGORIES:
                    assert await pilot.click(checkboxes[category])
            await pilot.pause()
            assert view.in_out_only
            assert not request.display and not thought.display and not plain.display
            assert incoming.display and outgoing.display and long_output.display
            assert [leaf.display for leaf in leaves] == [True, False, False, True]
            assert all(leaf.display for page in long_output._paged.pages for leaf in page.children), (
                "Nested pager lost routed output because its synthetic leaf has no route metadata")

            new_thought = AgentThought("LATE_THOUGHT")
            new_incoming = IncomingMessage("peer", "LATE_INCOMING", "owner")
            await view.contents.mount(new_thought, new_incoming)
            await pilot.pause()
            assert not new_thought.display and new_incoming.display
            # A bounded tail can contain no routed events. The earlier-history
            # control must still let the reader reach routed messages beyond it.
            older_event = TranscriptEvent("sent", "EARLIER_ROUTED_OUTPUT", routing=TurnRouting(
                (), MessageRoute("owner", ("peer",))))
            page_cursor = TranscriptCursor("earlier-fixture", 4)
            tail_cursor = TranscriptCursor("earlier-fixture", 8)
            calls = []

            async def load_earlier(**kwargs):
                calls.append(kwargs)
                return TranscriptPage((older_event,), TranscriptCursor("earlier-fixture", 0),
                                      page_cursor, False, True)

            tail = TranscriptHistory(TranscriptPage(
                (TranscriptEvent("thinking", "NONROUTED_TAIL"),),
                page_cursor, tail_cursor, True, False), loader=load_earlier)
            tail._loading = True  # Isolate the explicit earlier-history action.
            await view.contents.mount(tail)
            await pilot.pause()
            tail._loading = False
            tail.older.action_earlier()
            async with asyncio.timeout(5):
                while tail._loading or not calls:
                    await pilot.pause(.02)
            assert calls[0]["before"] == page_cursor
            assert tail._filter_overlay is not None
            assert any(leaf.display and leaf.fragment.events[0].text == "EARLIER_ROUTED_OUTPUT"
                       for leaf in tail._filter_overlay.children)
            view.displayed_transcript_cursor = cursor
            with patch.object(app.coordination_wire, "mark_thread_view_read") as mark:
                await app.mark_visible_thread_read()
                assert not mark.called, "Hidden replies were acknowledged as displayed"

            await app.new_session_screen(app.get_main_screen)
            await pilot.pause()
            assert not app.screen.conversation.in_out_only
            await app.switch_mode(owner_mode)
            await pilot.pause()
            assert view.in_out_only and all(checkboxes[category].value == (category in IN_OUT_CATEGORIES)
                                           for category in MESSAGE_CATEGORIES)
            assert view.prompt.text == "Unsent draft survives filtering"
            for category in MESSAGE_CATEGORIES:
                if category not in IN_OUT_CATEGORIES:
                    assert await pilot.click(checkboxes[category])
            await pilot.pause()
            assert not view.in_out_only
            assert all(block.display for block in (request, thought, plain, incoming, outgoing, new_thought))
            assert all(leaf.display for leaf in leaves)
            assert request.is_attached and history.pages[0].page.events == events
            assert view.window.scroll_y == full_scroll, (view.window.scroll_y, full_scroll)
            assert view.prompt.text == "Unsent draft survives filtering"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("in/out only: typed live/saved routes, nested paged bodies, late arrivals, per-view toggle, drafts and unread preserved")


if __name__ == "__main__":
    asyncio.run(main())
