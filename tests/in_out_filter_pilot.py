"""Native thread in/out filtering preserves routed bodies and reversible history."""
from runtime_fixture import coordination_update

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms.comms import wire
from agent_comms.messages import Message, MessageType
from agent_comms.routing import MessageRoute, TurnRouting
from agent_comms.threads import Thread
from agent_comms.transcript_events import (
    AssistantTranscript,
    SentTranscript,
    ThinkingTranscript,
    UserTranscript,
)
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from comms_boundary_fixture import coordination_fact
from runtime_fixture import ToadApp
from textual.widgets import Checkbox, Static

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse, ResponseDelivery
from toad.widgets.agent_thought import AgentThought
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.message_filter import IN_OUT_CATEGORIES, MESSAGE_CATEGORIES
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar
from toad.widgets.message_filter import MessageCategory, RoutedMessage
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.user_input import UserInput


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-in-out-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        comms = wire(root / "wire")
        for name in ("owner", "peer"):
            comms.threads.register(Thread(name, frozenset({"team"}), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(130, 44)) as pilot:
            await pilot.pause()
            owner_mode = app.current_mode
            screen = app.screen
            await screen.on_coordination_update(CoordinationUpdate(
                thread="owner", wire_root=str(root / "wire"), persistence="persistent", transport="stdio"))
            right = screen.query_one("#thread-sidebar", SideBar)
            right.reveal()
            await right.wait_content_ready()
            tree = screen.query_one(ThreadCommsSidebar)
            panel = tree.query_ancestor(SideBarCollapsible)
            panel.collapsed = False
            await pilot.pause()
            async with asyncio.timeout(5):
                while tree._snapshot is None:
                    await pilot.pause(.02)
            checkboxes = {category: tree.query_one(f"#filter-{category.declared_name}", Checkbox)
                          for category in MessageCategory.members_with(MessageCategory)}
            assert all(checkbox.display and checkbox.value for checkbox in checkboxes.values())
            owner_label = tree.query_one(".relationship-context", Static).render()
            assert any(("bold" in str(span.style) for span in owner_label.spans))
            sort = panel.query_one(RelationshipSort)
            assert sort.region.y == panel.query_one("CollapsibleTitle").region.y
            assert not tree.query(RelationshipSort), (
                "Sort remained inside a relationship group"
            )
            view = screen.conversation
            view.prompt.text = "Unsent draft survives filtering"
            incoming = IncomingMessage("peer", "INCOMING_BODY", "owner")
            outgoing = AgentResponse("OUTGOING_BODY", delivery=ResponseDelivery.from_route(MessageRoute("owner", ("peer",))))
            thought = AgentThought("PRIVATE_THOUGHT")
            plain = AgentResponse(
                "Plain answer containing [FROM] and [TO] is not routed"
            )
            request = UserInput("Ordinary user prompt")
            await view.contents.mount(request, thought, plain, incoming, outgoing)
            long_output = AgentResponse(delivery=ResponseDelivery.from_route(MessageRoute("owner", ("#team",))))
            await view.contents.mount(long_output)
            await long_output.update(
                "\n\n".join((f"ROUTED_PARAGRAPH_{i}" for i in range(100)))
            )
            await pilot.pause()
            assert long_output._paged is not None
            message = Message("peer", "owner", "SAVED_INCOMING", MessageType.INFO)
            events = (
                UserTranscript(message.body, routing=TurnRouting((message,), None)),
                ThinkingTranscript("SAVED_THOUGHT"),
                AssistantTranscript("SAVED_UNROUTED"),
                SentTranscript(
                    "SAVED_OUTGOING",
                    routing=TurnRouting((), MessageRoute("owner", ("peer",))),
                ),
            )
            cursor = TranscriptCursor("fixture", 0)
            history = TranscriptHistory(
                TranscriptPage(events, cursor, cursor, False, False)
            )
            await view.contents.mount(history)
            await pilot.pause()
            leaves = list(history.pages[0].children)
            assert len(leaves) == 4
            view.window.release_anchor()
            view.window.scroll_to(
                y=min(7, view.window.max_scroll_y), animate=False, immediate=True
            )
            await pilot.pause()
            full_scroll = view.window.scroll_y
            for category in MessageCategory.members_with(MessageCategory):
                if category not in frozenset(MessageCategory.members_with(RoutedMessage)):
                    assert await pilot.click(checkboxes[category])
            await pilot.pause()
            assert view.visible_categories == frozenset(MessageCategory.members_with(RoutedMessage))
            assert not request.display and not thought.display and not plain.display
            assert incoming.display and outgoing.display and long_output.display
            assert [leaf.display for leaf in leaves] == [True, False, False, True]
            assert all(
                (
                    leaf.display
                    for page in long_output._paged.pages
                    for leaf in page.children
                )
            ), (
                "Nested pager lost routed output because its synthetic leaf has no route metadata"
            )
            new_thought = AgentThought("LATE_THOUGHT")
            new_incoming = IncomingMessage("peer", "LATE_INCOMING", "owner")
            await view.contents.mount(new_thought, new_incoming)
            await pilot.pause()
            assert not new_thought.display and new_incoming.display
            older_event = SentTranscript(
                "EARLIER_ROUTED_OUTPUT",
                routing=TurnRouting((), MessageRoute("owner", ("peer",))),
            )
            page_cursor = TranscriptCursor("earlier-fixture", 4)
            tail_cursor = TranscriptCursor("earlier-fixture", 8)
            calls = []

            async def load_earlier(**kwargs):
                calls.append(kwargs)
                return TranscriptPage(
                    (older_event,),
                    TranscriptCursor("earlier-fixture", 0),
                    page_cursor,
                    False,
                    True,
                )

            tail = TranscriptHistory(
                TranscriptPage(
                    (ThinkingTranscript("NONROUTED_TAIL"),),
                    page_cursor,
                    tail_cursor,
                    True,
                    False,
                ),
                loader=load_earlier,
            )
            tail._loading = True
            await view.contents.mount(tail)
            await pilot.pause()
            tail._loading = False
            tail.older.action_earlier()
            async with asyncio.timeout(5):
                # A lookahead read may finish before the explicit UI action.
                # Wait for publication, not merely for source I/O to occur.
                while (tail.filter.overlay is None or not any(
                    leaf.fragment.events[0].text == "EARLIER_ROUTED_OUTPUT"
                    for leaf in tail.filter.overlay.fragment_views
                )):
                    await pilot.pause(.02)
            assert calls[0]["before"] == page_cursor
            assert tail.filter.overlay is not None
            assert any(leaf.display and leaf.fragment.events[0].text == "EARLIER_ROUTED_OUTPUT"
                       for leaf in tail.filter.overlay.fragment_views)
            view.transcript.displayed_cursor = cursor
            with patch.object(
                app.coordination_wire.views, "mark_thread_view_read"
            ) as mark:
                await app.mark_visible_thread_read()
                assert not mark.called, "Hidden replies were acknowledged as displayed"
            await app.new_session_screen(app.get_main_screen)
            await pilot.pause()
            assert not app.screen.conversation.visible_categories == frozenset(MessageCategory.members_with(RoutedMessage))
            await app.switch_mode(owner_mode)
            await pilot.pause()
            assert view.visible_categories == frozenset(MessageCategory.members_with(RoutedMessage)) and all(checkboxes[category].value == (category in frozenset(MessageCategory.members_with(RoutedMessage)))
                                           for category in MessageCategory.members_with(MessageCategory))
            assert view.prompt.text == "Unsent draft survives filtering"
            for category in MessageCategory.members_with(MessageCategory):
                if category not in frozenset(MessageCategory.members_with(RoutedMessage)):
                    assert await pilot.click(checkboxes[category])
            await pilot.pause()
            assert view.visible_categories != frozenset(MessageCategory.members_with(RoutedMessage))
            assert all(block.display for block in (request, thought, plain, incoming, outgoing, new_thought))
            assert all(leaf.display for leaf in leaves)
            assert request.is_attached and history.pages[0].page.events == events
            assert view.window.scroll_y == full_scroll, (
                view.window.scroll_y,
                full_scroll,
            )
            assert view.prompt.text == "Unsent draft survives filtering"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "in/out only: typed live/saved routes, nested paged bodies, late arrivals, per-view toggle, drafts and unread preserved"
    )


if __name__ == "__main__":
    asyncio.run(main())
