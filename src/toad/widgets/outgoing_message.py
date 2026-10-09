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
from toad.markdown_preparation import PreparedContentRange, PreparedMarkdownPart


class OutgoingMessage(WireMessageHandling, ConversationBlock, CategorizedBlock, VerticalGroup):
    DEFAULT_CLASSES = "block"

    def __init__(self, event: SentTranscript, *, show_header: bool = True,
                 markdown_part: PreparedMarkdownPart | None = None,
                 prepared_content: PreparedContentRange | None = None, paginate: bool = True):
        super().__init__()
        self.event = event
        self.show_header = show_header
        self.markdown_part = markdown_part
        self._content_transfer = prepared_content
        self.paginate = paginate

    @property
    def message_reference(self):
        return self.event.source

    @property
    def message_category(self):
        return OutboundCategory

    def compose(self) -> ComposeResult:
        yield AgentResponse(self.event.text,
                            markdown_part=self.markdown_part,
                            prepared_content=self._content_transfer, paginate=self.paginate,
                            delivery=ResponseDelivery.from_route(self.event.routing.reply),
                            show_divider=self.show_header,
                            clock=MessageClock.recorded(self.event.timestamp))
        if self.handling_references:
            yield MessageNotifications()

    @property
    def prepared_content(self):
        body = self.query_one_optional(AgentResponse)
        return self._content_transfer if body is None else body.prepared_content

    def retain_transcript_source(self, fragment):
        fragment.prepared_content = self.retain_sources()

    def retain_sources(self):
        body = self.query_one_optional(AgentResponse)
        return self._content_transfer if body is None else body.retain_sources()
