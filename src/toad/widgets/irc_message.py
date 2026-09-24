"""Compact wire messages with keyboard- and pointer-accessible routing names."""

import time
from textual import events
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.style import Style
from textual.widgets import Static
from agent_comms import Message
from toad.widgets.comms_sidebar import SelectTarget
from toad.widgets.inline_message import inline_message


class ThreadLink(Static, can_focus=True):
    BINDINGS = [("enter,space", "open_target", "Open thread")]
    DEFAULT_CSS = """
    ThreadLink { width: auto; max-width: 25%; height: auto; color: $accent; pointer: pointer; }
    ThreadLink:hover, ThreadLink:focus { text-style: underline; background: $accent 20%; }
    """

    def __init__(self, target: str):
        self.target = target
        super().__init__(target, markup=False)

    def action_open_target(self):
        self.post_message(
            SelectTarget(
                self.target, "channel" if self.target.startswith("#") else "thread"
            )
        )

    def on_click(self, event: events.Click):
        if event.button == 1:
            event.stop()
            self.action_open_target()


class MembershipNotice(Static):
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


class IRCMessage(HorizontalGroup, can_focus=True):
    BINDINGS = [
        ("enter", "open_sender", "Open sender"),
        ("shift+enter", "open_destination", "Open destination"),
    ]
    DEFAULT_CSS = """
    IRCMessage {
        width: 1fr; height: auto; margin: 0; padding: 0;
        .irc-time { width: 7; height: 1; color: $text-muted; }
        IRCMessageText { width: 1fr; height: auto; text-wrap: wrap; }
    }
    """

    def __init__(self, message: Message):
        super().__init__()
        self.message = message
        self.source = message.body

    def compose(self) -> ComposeResult:
        message = self.message
        yield Static(
            time.strftime("%H:%M", time.localtime(message.timestamp)),
            markup=False,
            classes="irc-time",
        )
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

    @staticmethod
    def _link(target: str) -> Content:
        return Content.styled(target, "$accent").stylize(
            Style.from_meta({"@click": ("open_target", (target,))})
        )

    def mentioned_body(self) -> Content:
        return inline_message(self.message.body, self.message.mentions)

    def action_open_target(self, target: str):
        self.post_message(
            SelectTarget(target, "channel" if target.startswith("#") else "thread")
        )

    def action_open_sender(self):
        self.action_open_target(self.message.sender)

    def action_open_destination(self):
        self.action_open_target(self.message.target)

    def get_block_content(self, destination: str) -> str:
        return f"{self.message.sender} → {self.message.target}: {self.message.body}"


class WireMarkdownMessage(VerticalGroup):
    DEFAULT_CLASSES = "block"

    def __init__(self, message: Message):
        super().__init__()
        self.message = message
        self.source = message.body

    def compose(self) -> ComposeResult:
        from toad.widgets.agent_response import AgentResponse

        with HorizontalGroup():
            yield ThreadLink(self.message.sender)
            yield Static(" → ", markup=False, expand=False)
            yield ThreadLink(self.message.target)
            yield Static(
                time.strftime(" · %H:%M", time.localtime(self.message.timestamp)),
                expand=False,
            )
        yield AgentResponse(self.message.body)
        if self.message.mentions:
            with HorizontalGroup():
                yield Static("Mentioned: ", expand=False)
                for target in dict.fromkeys(mention.thread for mention in self.message.mentions):
                    yield ThreadLink(target)
