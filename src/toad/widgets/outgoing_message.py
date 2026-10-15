"""A message this thread just sent on the bus, drawn live."""

from functools import cached_property

from agent_comms.transcript_events import SentTranscript
from textual.app import ComposeResult
from textual.containers import VerticalGroup

from toad.block_navigation import ConversationBlock
from toad.message_rows import MessageRow
from toad.response_delivery import ResponseDelivery
from toad.widgets.agent_response import AgentResponse
from toad.widgets.message_divider import MessageClock
from toad.widgets.message_filter import CategorizedBlock, OutboundCategory
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.committed_presentation import CommitParticipant, OutgoingMessageClaim
from toad.widgets.transcript_lines import MessageRowBlock
from toad.widgets.wire_message_handling import WireMessageHandling


class OutgoingMessage(MessageRowBlock, WireMessageHandling, ConversationBlock, CommitParticipant, CategorizedBlock, VerticalGroup):
    DEFAULT_CLASSES = "block"

    def __init__(self, event: SentTranscript, *, show_header: bool = True):
        super().__init__()
        self.event = event
        self.show_header = show_header

    @classmethod
    async def present(cls, conversation, event):
        if conversation.transcript.covers_outgoing(event):
            return
        if any(body.event.outgoing_sources == event.outgoing_sources
               for body in conversation.contents.query_children(cls)):
            return
        body = await conversation.post(cls(event), new_block=True)
        # A canonical page may arrive while native mount yields. Use the same
        # retirement owner, not a second seen set or a high-water approximation.
        if conversation.transcript.covers_outgoing(event):
            await conversation.transcript.retire_presentations(
                conversation.contents, conversation.output, [body])

    @property
    def commit_claim(self):
        return OutgoingMessageClaim(self.event)

    @cached_property
    def message_row(self) -> MessageRow:
        return MessageRow.sent(self.event)

    @property
    def message_reference(self):
        return self.event.source

    @property
    def message_category(self):
        return OutboundCategory

    def compose(self) -> ComposeResult:
        yield AgentResponse(self.event.text,
                            delivery=ResponseDelivery.from_route(self.event.routing.reply),
                            show_divider=self.show_header,
                            clock=MessageClock.recorded(self.event.timestamp))
        if self.handling_references:
            yield MessageNotifications()
