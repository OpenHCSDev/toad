"""A prepared body of the canonical original outbound wire record."""

from agent_comms.transcript_events import SentTranscript
from textual.app import ComposeResult
from textual.containers import VerticalGroup

from toad.block_navigation import ConversationBlock
from toad.response_delivery import ResponseDelivery
from toad.widgets.agent_response import AgentResponse
from toad.widgets.message_divider import MessageClock
from toad.widgets.message_filter import CategorizedBlock, OutboundCategory
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.wire_message_handling import WireMessageHandling
from toad.markdown_preparation import PreparedMarkdownPart


class OutgoingMessage(WireMessageHandling, ConversationBlock, CategorizedBlock, VerticalGroup):
    DEFAULT_CLASSES = "block"

    def __init__(self, event: SentTranscript, *, show_header: bool = True,
                 markdown_part: PreparedMarkdownPart | None = None):
        super().__init__()
        self.event = event
        self.show_header = show_header
        self.markdown_part = markdown_part

    @property
    def message_reference(self):
        return self.event.source

    @property
    def message_category(self):
        return OutboundCategory

    def compose(self) -> ComposeResult:
        yield AgentResponse(self.event.text,
                            markdown_part=self.markdown_part,
                            delivery=ResponseDelivery.from_route(self.event.routing.reply),
                            show_divider=self.show_header,
                            clock=MessageClock.recorded(self.event.timestamp))
        if self.handling_references:
            yield MessageNotifications()
