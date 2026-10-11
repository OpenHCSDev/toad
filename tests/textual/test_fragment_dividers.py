"""Textual-facing: a long saved or live message paginated into several pieces draws one divider, whether as prepared history lines or as a live widget."""

from agent_comms.message_reference import MessageReference
from agent_comms.messages import Message, MessageType
from agent_comms.routing import MessageRoute, TurnRouting
from agent_comms.transcript_events import IncomingTranscript, NoticeTranscript, SentTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from toad.line_blocks import Divider
from toad.widgets.agent_response import AgentResponse
from toad.widgets.message_divider import MessageDivider
from toad.widgets.transcript_fragments import transcript_fragments

TEXT = "## Context compacted\n\n" + "\n\n".join(
    f"### Section {index}\n" + "A retained fact. " * 38 for index in range(8))
CURSOR = TranscriptCursor("", 0)


def dividers_in(event):
    fragments = transcript_fragments(TranscriptPage((event,), CURSOR, CURSOR, False, False).events)
    assert len(fragments) >= 4
    return [block for fragment in fragments for block in fragment.line_blocks if isinstance(block, Divider)]


def test_saved_notice_pieces_share_one_divider():
    assert len(dividers_in(NoticeTranscript(TEXT))) == 1, "saved notice got repeated timestamps"


def test_saved_sent_message_pieces_share_one_divider_naming_its_route():
    route = MessageRoute("worker", ("#updates",))
    dividers = dividers_in(SentTranscript(
        TEXT, routing=TurnRouting(reply=route), source=MessageReference(1, "fragment-outbound")))
    assert len(dividers) == 1 and "#updates" in dividers[0].label


def test_saved_incoming_message_pieces_share_one_divider_naming_its_sender():
    incoming = Message("worker", "#updates", TEXT, MessageType.INFO)
    dividers = dividers_in(IncomingTranscript(
        TEXT, route=MessageRoute(incoming.sender, (incoming.target,)), source=incoming.reference))
    assert len(dividers) == 1 and "worker" in dividers[0].label


async def test_live_message_has_one_divider(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        live = await ui.conversation.post(AgentResponse(TEXT))
        await ui.step()
        assert len(live.query(MessageDivider)) == 1, "live message got nested timestamps"
