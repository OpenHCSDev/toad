"""An attributed wire message with native thread navigation."""

from textual.app import ComposeResult
from textual.containers import VerticalGroup
from toad.widgets.route_header import RouteHeader
from toad.widgets.message_divider import MessageDivider
from agent_comms import MessageRoute
from toad.widgets.message_filter import CategorizedBlock, MessageCategory


class IncomingSender(RouteHeader):

    def __init__(self, sender: str, target: str | None = None) -> None:
        self.sender = sender
        self.target = target
        route = MessageRoute(sender, (target,) if target else ())
        super().__init__(route, incoming=True)

    def action_open_thread(self) -> None:
        self.action_open_target(self.sender)


class IncomingMessage(CategorizedBlock, VerticalGroup):
    DEFAULT_CLASSES = "block"

    @property
    def message_category(self) -> MessageCategory:
        return MessageCategory.INBOUND

    def __init__(self, sender: str, text: str, target: str | None = None) -> None:
        super().__init__()
        self.sender = sender
        self.text = text
        self.target = target

    def compose(self) -> ComposeResult:
        from toad.widgets.agent_response import AgentResponse

        yield MessageDivider(f"Inbound · @{self.sender}")
        yield IncomingSender(self.sender, self.target)
        yield AgentResponse(self.text, show_divider=False).add_class("routed-body")

    def get_block_content(self, destination: str) -> str:
        route = MessageRoute(self.sender, (self.target,) if self.target else ())
        return f"{route.incoming_label}\n{self.text}"
