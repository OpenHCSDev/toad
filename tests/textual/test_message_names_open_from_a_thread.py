"""Textual-facing: in a thread's own view, the sender and destination named above a bus message open what they name, in saved history and on a message just sent, as they do in a channel."""

from agent_comms.message_reference import MessageReference
from agent_comms.routing import MessageRoute, TurnRouting
from agent_comms.transcript_events import IncomingTranscript, SentTranscript
from agent_comms.transcript_sources import TranscriptCursor, NativeCursor
from agent_comms.transcripts import TranscriptPage

from toad.line_blocks import OpenTarget
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.outgoing_message import OutgoingMessage
from toad.widgets.transcript_history import TranscriptHistory


def sent(text, number):
    return SentTranscript(text, source=MessageReference(number, f"sent-{number}"), timestamp=1_700_000_000.0 + number,
                          routing=TurnRouting(reply=MessageRoute("owner", ("#team",))))


async def test_names_above_saved_and_live_messages_open_the_thread_and_the_channel(workspace):
    workspace.thread("owner", "team", running=True)
    workspace.thread("peer", "team", running=True)
    wire_root = str(workspace.roots.wire)
    cursor = NativeCursor("fixture", 1)
    page = TranscriptPage((
        IncomingTranscript("SAVED_INCOMING", route=MessageRoute("peer", ("owner",)), timestamp=1_700_000_000.0,
                           source=MessageReference(1, "incoming-1")),
        sent("SAVED_SENT", 2),
    ), cursor, cursor, False, False)
    async with workspace.app(size=(110, 38)) as ui:
        app, _pilot = ui.textual
        owner = ui.selected_tab
        app.selected_session.initial_coordination_root = wire_root
        app.selected_session._comms_thread = "owner"
        peer = await ui.new_session()
        app.selected_session.initial_coordination_root = wire_root
        app.selected_session._comms_thread = "peer"
        await ui.select_tab(owner)
        view = ui.conversation
        await view.post(TranscriptHistory(page))
        await view.post(OutgoingMessage(sent("LIVE_SENT", 3)))
        await ui.until_shows("LIVE_SENT")

        # Saved history: each name above a message is its own link, and no caption stands in for the route.
        await ui.until(lambda: ui.link_at("peer → owner") == OpenTarget("peer").click, why="the saved sender as a link")
        assert ui.link_at("owner · ") == OpenTarget("owner").click
        # The message just sent draws the same header: owner → #team, saved first, then live.
        for occurrence in (0, 1):
            assert ui.link_at("owner → #team", occurrence=occurrence) == OpenTarget("owner").click
            assert ui.link_at("#team · ", occurrence=occurrence) == OpenTarget("#team").click
        assert not any(caption in ui.visible_text() for caption in ("Sent →", "Outbound", "Inbound", " TO "))

        await ui.click("peer → owner")
        await ui.until(lambda: ui.selected_tab == peer, seconds=3, why="the sender's open tab")

        for occurrence in (0, 1):
            await ui.select_tab(owner)
            await ui.click("#team · ", occurrence=occurrence)
            await ui.until(lambda: ui.selected_tab not in (owner, peer), seconds=5, why="the channel's tab")
            chat = app.screen.query_one(CommsChatView)
            assert chat.target == "#team"
            await ui.close_tab(ui.selected_tab)
        assert ui.failure() is None
