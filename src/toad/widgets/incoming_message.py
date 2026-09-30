from toad.block_navigation import ConversationBlock
"""An attributed wire message with native thread navigation."""

from toad.widgets.message_filter import InboundCategory

from textual.app import ComposeResult
from textual.containers import VerticalGroup
from toad.widgets.route_header import RouteHeader
from toad.widgets.message_divider import MessageDivider, MessageClock, LiveMessageClock
from agent_comms.routing import MessageRoute
from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import CommitParticipant, SequenceClaim
from agent_comms.message_reference import MessageReference
from toad.widgets.wire_message_handling import WireMessageHandling
from toad.widgets.message_notifications import MessageNotifications



class IncomingSender(RouteHeader):

    def __init__(self, sender: str, target: str | None = None) -> None:
        self.sender = sender
        self.target = target
        route = MessageRoute(sender, (target,) if target else ())
        super().__init__(route, incoming=True)

    def action_open_thread(self) -> None:
        self.action_open_target(self.sender)


class IncomingMessage(WireMessageHandling, ConversationBlock, CommitParticipant, CategorizedBlock, VerticalGroup):
    DEFAULT_CLASSES = "block"
    DEFAULT_CSS = """
    IncomingMessage .assignment-handling {
        height: 1; color: $text-muted; text-overflow: ellipsis;
    }
    """

    @property
    def message_category(self) -> type[MessageCategory]:
        return InboundCategory

    @property
    def commit_claim(self) -> SequenceClaim:
        return SequenceClaim(self.sequence)

    def __init__(self, sender: str, text: str, target: str | None = None,
                 *, show_header: bool = True, source: MessageReference | None = None, clock: MessageClock = LiveMessageClock()) -> None:
        super().__init__()
        self.sender = sender
        self.text = text
        self.target = target
        self.show_header = show_header
        self.source = source
        self.clock = clock

    @property
    def message_reference(self):
        return self.source

    @property
    def sequence(self):
        return self.source.seq if self.source is not None else None

    def compose(self) -> ComposeResult:
        from toad.widgets.agent_response import AgentResponse

        if self.show_header:
            yield MessageDivider(f"Inbound · @{self.sender}", clock=self.clock)
            yield IncomingSender(self.sender, self.target)
        yield AgentResponse(self.text, show_divider=False).add_class("routed-body")
        if self.handling_references:
            yield MessageNotifications()

    def get_clipboard_text(self) -> str:
        route = MessageRoute(self.sender, (self.target,) if self.target else ())
        return f"{route.incoming_label}\n{self.text}"
