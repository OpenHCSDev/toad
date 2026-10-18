"""A message this thread just sent on the bus, drawn live."""

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
from toad.notification_status import CheckedNotifications, NotificationStatus
from toad.widgets.committed_presentation import CommitParticipant, OutgoingMessageClaim


class OutgoingMessage(MessageRowBlock, CommitParticipant, ConversationBlock, CategorizedBlock, VerticalGroup):
    DEFAULT_CLASSES = "block"

    def __init__(self, publication: PublishedSentMessage, *, row: MessageRow, binding, request, show_header: bool = True):
        super().__init__()
        self.publication = publication
        self.message_row = row
        self.binding = binding
        self.request = request
        self.show_header = show_header

    @property
    def commit_claim(self):
        return OutgoingMessageClaim(self.publication)

    @property
    def message_reference(self):
        return self.publication.message.source

    def notification_targets(self):
        return (self,) if self.show_header and self.display else ()

    @property
    def notification_references(self):
        return (self.message_reference,)

    async def show_notifications(self, results):
        await self.show_notification_status(CheckedNotifications.for_references(self.notification_references, results))

    async def show_notification_status(self, status: NotificationStatus):
        if self.is_attached:
            self.query_one(MessageNotifications).show(status)

    @property
    def message_category(self):
        return OutboundCategory

    def compose(self) -> ComposeResult:
        message = self.publication.message
        if self.show_header:
            yield MessageRowDivider(self.message_row, clock=LiveMessageClock())
        yield AgentResponse(message.text,
                            delivery=ResponseDelivery.from_route(self.message_row.route),
                            show_divider=False,
                            clock=LiveMessageClock())
        if self.show_header:
            yield MessageNotifications()
