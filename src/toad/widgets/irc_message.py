from toad.block_navigation import ConversationBlock
"""Compact wire messages with keyboard- and pointer-accessible routing names."""

from toad.navigation_target import linked_target

from textual import events
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.style import Style
from textual.widget import Widget
from textual.message import Message as UIMessage
from textual.widgets import Static
from agent_comms.messages import Message
from agent_comms import HistoricalMessage
from toad.widgets.comms_sidebar import SelectTarget
from toad.widgets.inline_message import inline_message
from toad.widgets.message_divider import MessageDivider
from toad.widgets.message_notifications import MessageNotifications


class SelectHistoricalIdentity(UIMessage):
    def __init__(self, name: str, source: str):
        super().__init__()
        self.name = name
        self.source = source


class ThreadLink(Static, can_focus=True):
    BINDINGS = [("enter,space", "open_target", "Open thread")]
    DEFAULT_CSS = """
    ThreadLink { width: auto; max-width: 25%; height: auto; color: $accent; pointer: pointer; }
    ThreadLink:hover, ThreadLink:focus { text-style: underline; background: $accent 20%; }
    """

    def __init__(self, target: str, history_source: str | None = None):
        self.target = target
        self.history_source = history_source
        super().__init__(target, markup=False)

    def action_open_target(self):
        if self.history_source and not self.target.startswith("#"):
            self.post_message(SelectHistoricalIdentity(self.target, self.history_source))
            return
        self.post_message(
            SelectTarget(linked_target(self.target))
        )

    def on_click(self, event: events.Click):
        if event.button == 1:
            event.stop()
            self.action_open_target()


class MembershipNotice(ConversationBlock, Static):
    DEFAULT_CLASSES = "block"
    DEFAULT_CSS = "MembershipNotice { height: auto; color: $text-muted; margin: 0; }"

    def __init__(self, message: Message):
        super().__init__("— " + message.body, markup=False)
        self.message = message

    def get_block_content(self, destination: str) -> str:
        return self.message.body


class IRCMessageText(Static):
    """One wrapping, linked sender/destination/message block beside the time."""

    def action_open_target(self, target: str):
        self.query_ancestor(IRCMessage).action_open_target(target)

    def action_open_url(self, url: str):
        self.app.open_url(url)


class IRCMessage(ConversationBlock, VerticalGroup, can_focus=True):
    BINDINGS = [
        ("enter", "open_sender", "Open sender"),
        ("shift+enter", "open_destination", "Open destination"),
    ]
    DEFAULT_CSS = """
    IRCMessage {
        width: 1fr; height: auto; margin: 0; padding: 0;
        .irc-body { width: 1fr; height: auto; }
        IRCMessageText { width: 1fr; height: auto; text-wrap: wrap; }
    }
    """

    def __init__(self, message: Message, *, direction: str = "Inbound"):
        super().__init__()
        self.message = message
        self.direction = (
            f"History · {message.source.original_root} · @{message.sender} incarnation {message.sender_created_at}"
            if isinstance(message, HistoricalMessage) else direction
        )
        self.source = message.body

    def compose(self) -> ComposeResult:
        message = self.message
        yield MessageDivider(self.direction, timestamp=message.timestamp)
        with HorizontalGroup(classes="irc-body"):
            yield IRCMessageText(
                Content.assemble(
                    self._link(message.sender),
                    (" → ", "$text-muted"),
                    self._link(message.target),
                    " ",
                    self.mentioned_body(),
                ),
                markup=False,
            )
        yield MessageNotifications()

    @staticmethod
    def _link(target: str) -> Content:
        return Content.styled(target, "$accent").stylize(
            Style.from_meta({"@click": ("open_target", (target,))})
        )

    def mentioned_body(self) -> Content:
        return inline_message(self.message.body, self.message.mentions)

    def read_ack_widget(self) -> Widget:
        """Only the text block can authorize a read, never its divider."""
        return self.query_one(IRCMessageText)

    def action_open_target(self, target: str):
        if isinstance(self.message, HistoricalMessage) and not target.startswith("#"):
            self.post_message(SelectHistoricalIdentity(target, self.message.source.key))
            return
        self.post_message(
            SelectTarget(linked_target(target))
        )

    def action_open_sender(self):
        self.action_open_target(self.message.sender)

    def action_open_destination(self):
        self.action_open_target(self.message.target)

    def get_block_content(self, destination: str) -> str:
        return f"{self.message.sender} → {self.message.target}: {self.message.body}"


class WireMarkdownMessage(ConversationBlock, VerticalGroup):
    DEFAULT_CLASSES = "block"

    def __init__(self, message: Message, *, direction: str = "Inbound"):
        super().__init__()
        self.message = message
        self.direction = (
            f"History · {message.source.original_root} · @{message.sender} incarnation {message.sender_created_at}"
            if isinstance(message, HistoricalMessage) else direction
        )
        self.source = message.body

    def compose(self) -> ComposeResult:
        from toad.widgets.agent_response import AgentResponse

        yield MessageDivider(self.direction, timestamp=self.message.timestamp)
        source = self.message.source.key if isinstance(self.message, HistoricalMessage) else None
        with HorizontalGroup():
            yield ThreadLink(self.message.sender, source)
            yield Static(" → ", markup=False, expand=False)
            yield ThreadLink(self.message.target, source)
        yield AgentResponse(self.message.body, show_divider=False)
        if self.message.mentions:
            with HorizontalGroup():
                yield Static("Mentioned: ", expand=False)
                for target in dict.fromkeys(mention.thread for mention in self.message.mentions):
                    yield ThreadLink(target, source)
        yield MessageNotifications()

    def read_ack_widget(self) -> Widget:
        """Only the rendered message body can authorize a read."""
        from toad.widgets.agent_response import AgentResponse

        return self.query_one(AgentResponse)
