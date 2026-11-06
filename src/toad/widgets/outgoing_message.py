"""A message this thread just sent on the bus, drawn live."""

from agent_comms.sent_message import PublishedSentMessage
from textual.app import ComposeResult
from textual.containers import VerticalGroup

from toad.block_navigation import CategorizedBlock, SeparatedBlock
from toad.message_rows import MessageRow
from toad.response_delivery import ResponseDelivery
from toad.widgets.agent_response import AgentResponse
from toad.message_rows import LiveMessageClock
from toad.widgets.message_divider import MessageRowDivider
from agent_comms.ui_model.message_category import OutboundCategory
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.linked_rows import MessageRowBlock
from toad.widgets.message_row_owner import MessageRowOwner
from toad.notification_status import CheckedNotifications, MessageQueueEntry, NotificationStatus
from toad.commit_claims import CommitParticipant, OutgoingMessageClaim


class OutgoingMessage(MessageRowOwner, MessageRowBlock, CommitParticipant, SeparatedBlock, CategorizedBlock, VerticalGroup):
    def __init__(self, publication: PublishedSentMessage, *, row: MessageRow, binding, request, show_header: bool = True):
        super().__init__()
        self.publication = publication
        self.message_row = row
        self.binding = binding
        self.request = request
        self.message_dividers = (MessageRowDivider(row, clock=LiveMessageClock()),) if show_header else ()

    @property
    def commit_claim(self):
        return OutgoingMessageClaim(self.publication)

    @property
    def message_reference(self):
        return self.publication.message.source

    def notification_targets(self):
        return (self,) if self.message_dividers and self.display else ()

    def queue_entries(self) -> tuple[MessageQueueEntry, ...]:
        return (MessageQueueEntry(self.message_reference, self.query_one(MessageNotifications).status),)

    @property
    def notification_references(self):
        return (self.message_reference,)

    async def show_notifications(self, results):
        for status in CheckedNotifications.for_references(self.notification_references, results):
            if self.is_attached:
                self.query_one(MessageNotifications).show(status)

    async def show_notification_status(self, status: NotificationStatus):
        """A failed read; an answer already shown stays until a new answer replaces it."""
        if self.is_attached:
            feedback = self.query_one(MessageNotifications)
            feedback.show(feedback.status.failed(status))

    @property
    def message_category(self):
        return OutboundCategory

    def compose(self) -> ComposeResult:
        message = self.publication.message
        yield from self.message_dividers
        yield AgentResponse(message.text,
                            delivery=ResponseDelivery.from_route(self.message_row.route),
                            show_divider=False,
                            clock=LiveMessageClock())
        if self.message_dividers:
            yield MessageNotifications()
