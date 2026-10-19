"""Textual-facing: with the block cursor on a bus message in a thread's view, Enter offers "Open sender" and "Open destination" and they open what the header names, whether the message came from saved history, was just sent, or is a routed answer being written, as a channel's rows do."""

from agent_comms.message_reference import MessageReference
from agent_comms.routing import MessageRoute, TurnRouting
from agent_comms.transcript_events import IncomingTranscript, SentTranscript
from agent_comms.transcripts import NativeTranscriptCursor, TranscriptPage
from support.roots import FIXTURE_SNAPSHOT

from toad.response_delivery import RoutedResponse
from toad.widgets.agent_response import AgentResponse
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.menu import Menu
from toad.widgets.message_divider import MessageDivider
from toad.widgets.outgoing_message import OutgoingMessage
from toad.widgets.transcript_history import TranscriptHistory

OPEN = ["Open [u]s[/u]ender", "Open [u]d[/u]estination"]


def sent(text, number):
    return SentTranscript(text, source=MessageReference(number, f"sent-{number}"), timestamp=1_700_000_000.0 + number,
                          routing=TurnRouting(reply=MessageRoute("owner", ("#team",))))


def offered(view):
    """What the cursor's menu adds for the block it rests on."""
    return [item.description for item in view.navigation.cursor.get_block_menu()]


async def choose(ui, view, key):
    await ui.press("enter")
    await ui.until(lambda: bool(view.query(Menu)), why="the message's menu")
    await ui.press(key)
    await ui.until(lambda: not view.query(Menu), why="the menu to close")


async def test_enter_on_a_saved_a_sent_and_a_routed_live_message_opens_its_sender_and_destination(workspace):
    workspace.thread("owner", "team", running=True)
    workspace.thread("peer", "team", running=True)
    wire_root = str(workspace.roots.wire)
    cursor = NativeTranscriptCursor("fixture", 1)
    page = TranscriptPage((
        IncomingTranscript("SAVED_INCOMING", route=MessageRoute("peer", ("owner",)), timestamp=1_700_000_000.0,
                           source=MessageReference(1, "incoming-1")),
        sent("SAVED_SENT", 2),
    ), cursor, cursor, False, False, FIXTURE_SNAPSHOT)
    async with workspace.app(size=(110, 40)) as ui:
        app, _pilot = ui.textual
        owner = ui.selected_tab
        app.selected_session.initial_coordination_root = wire_root
        app.selected_session._comms_thread = "owner"
        peer = await ui.new_session()
        app.selected_session.initial_coordination_root = wire_root
        app.selected_session._comms_thread = "peer"
        await ui.select_tab(owner)
        view = ui.conversation
        history = TranscriptHistory(page)
        await view.post(history)
        live_sent = OutgoingMessage(sent("LIVE_SENT", 3))
        await view.post(live_sent)
        routed = AgentResponse("LIVE_ROUTED", delivery=RoutedResponse(MessageRoute("owner", ("peer",))))
        await view.post(routed)
        await ui.until_shows("LIVE_ROUTED")

        # Alt+Up walks from the prompt over the routed answer (its text, then its header), the sent message
        # and the two saved messages: each bus message offers the same two entries.
        seen = {}
        for _step in range(8):
            await ui.press("alt+up")
            block, cursor_ = view.cursor_block, view.navigation.cursor
            if block is routed and isinstance(cursor_.selected, MessageDivider):
                seen["routed"] = offered(view)
            elif block is live_sent:
                seen["sent"] = offered(view)
            elif block is history:
                seen[cursor_.fragment.events[0].text] = offered(view)
        assert seen == {"routed": OPEN, "sent": OPEN, "SAVED_SENT": OPEN, "SAVED_INCOMING": OPEN}

        # The cursor is on the oldest saved message, which peer sent: Enter, s opens peer's tab.
        assert view.navigation.cursor.fragment.events[0].text == "SAVED_INCOMING"
        await choose(ui, view, "s")
        await ui.until(lambda: ui.selected_tab == peer, seconds=3, why="the saved message's sender")

        # A click puts the cursor on the message just sent: Enter, d opens the channel it went to.
        await ui.select_tab(owner)
        await ui.click("LIVE_SENT")
        await ui.until(lambda: view.cursor_block is live_sent, why="the cursor on the sent message")
        await choose(ui, view, "d")
        await ui.until(lambda: ui.selected_tab not in (owner, peer), seconds=5, why="the sent message's channel")
        assert app.screen.query_one(CommsChatView).target == "#team"
        await ui.close_tab(ui.selected_tab)

        # The header of the routed answer, reached from the prompt: Enter, d opens peer's tab.
        await ui.select_tab(owner)
        view.focus_prompt()
        await ui.press("alt+up")
        await ui.press("alt+up")
        assert view.cursor_block is routed and isinstance(view.navigation.cursor.selected, MessageDivider)
        await choose(ui, view, "d")
        await ui.until(lambda: ui.selected_tab == peer, seconds=3, why="the routed answer's destination")
        assert ui.failure() is None
