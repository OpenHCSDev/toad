"""A message this thread just sent on the bus, drawn live."""

from functools import cached_property

from agent_comms.sent_message import PublishedSentMessage
from textual.app import ComposeResult
from textual.containers import VerticalGroup

from toad.block_navigation import ConversationBlock
from toad.message_rows import MessageRow
from toad.response_delivery import ResponseDelivery
from toad.widgets.agent_response import AgentResponse
from toad.widgets.message_divider import LiveMessageClock, MessageRowDivider
from toad.widgets.message_filter import CategorizedBlock, OutboundCategory
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.transcript_lines import MessageRowBlock
from toad.widgets.wire_message_handling import WireMessageHandling
from toad.widgets.committed_presentation import CommitParticipant, OutgoingMessageClaim


class OutgoingMessage(MessageRowBlock, WireMessageHandling, CommitParticipant, ConversationBlock, CategorizedBlock, VerticalGroup):
    DEFAULT_CLASSES = "block"

    def __init__(self, publication: PublishedSentMessage, *, binding, request, show_header: bool = True):
        super().__init__()
        self.publication = publication
        self.binding = binding
        self.request = request
        self.show_header = show_header

    @property
    def commit_claim(self):
        return OutgoingMessageClaim(self.publication)

    @cached_property
    def message_row(self) -> MessageRow:
        return MessageRow(self.publication.message, self.publication.scope.recipient.name)

    @property
    def message_reference(self):
        return self.publication.message.reference

    @property
    def message_category(self):
        return OutboundCategory

    def compose(self) -> ComposeResult:
        message = self.publication.message
        if self.show_header:
            yield MessageRowDivider(self.message_row, clock=LiveMessageClock())
        yield AgentResponse(message.body,
                            delivery=ResponseDelivery.from_route(self.message_row.route),
                            show_divider=False,
                            clock=LiveMessageClock())
        if self.handling_references:
            yield MessageNotifications()
