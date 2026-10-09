"""An attributed wire message with native thread navigation."""

from toad.block_navigation import ConversationBlock
from toad.widgets.message_filter import InboundCategory

from textual.app import ComposeResult
from textual.containers import VerticalGroup
from toad.widgets.route_header import RouteHeader
from toad.widgets.message_divider import MessageDivider, MessageClock
from agent_comms.transcript_events import IncomingTranscript
from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import CommitParticipant, SequenceClaim
from toad.widgets.wire_message_handling import WireMessageHandling
from toad.widgets.message_notifications import MessageNotifications
from toad.markdown_preparation import PreparedContentRange, PreparedMarkdownPart



class IncomingMessage(WireMessageHandling, ConversationBlock, CommitParticipant, CategorizedBlock, VerticalGroup):
    DEFAULT_CLASSES = "block"

    @property
    def message_category(self) -> type[MessageCategory]:
        return InboundCategory

    @property
    def commit_claim(self) -> SequenceClaim:
        return SequenceClaim(self.sequence)

    def __init__(self, event: IncomingTranscript, *, show_header: bool = True,
                 markdown_part: PreparedMarkdownPart | None = None,
                 prepared_content: PreparedContentRange | None = None, paginate: bool = True) -> None:
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
    def sequence(self):
        return self.event.source.seq

    def compose(self) -> ComposeResult:
        from toad.widgets.agent_response import AgentResponse

        if self.show_header:
            yield MessageDivider(f"Inbound · @{self.event.route.sender}",
                                 clock=MessageClock.recorded(self.event.timestamp))
            yield RouteHeader(self.event.route, incoming=True)
        yield AgentResponse(self.event.text, show_divider=False,
                            markdown_part=self.markdown_part, prepared_content=self._content_transfer,
                            paginate=self.paginate).add_class("routed-body")
        if self.handling_references:
            yield MessageNotifications()

    @property
    def prepared_content(self):
        from toad.widgets.agent_response import AgentResponse

        body = self.query_one_optional(AgentResponse)
        return self._content_transfer if body is None else body.prepared_content

    def retain_transcript_source(self, fragment):
        from toad.widgets.agent_response import AgentResponse

        body = self.query_one_optional(AgentResponse)
        fragment.prepared_content = self._content_transfer if body is None else body.retain_sources()

    def get_clipboard_text(self) -> str:
        return f"{self.event.route.incoming_label}\n{self.event.text}"
