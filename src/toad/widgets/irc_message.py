from toad.core.input_events import SelectHistoricalIdentity
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from toad.block_navigation import ConversationBlock
"""Compact wire messages with keyboard- and pointer-accessible routing names."""

from toad.navigation_target import linked_target

from textual import events
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup
from textual.widget import Widget
from textual.widgets import Static
from agent_comms.messages import Message
from agent_comms import HistoricalMessage
from toad.core.input_events import SelectTarget
from toad.widgets.inline_message import IRCMessageSource
from toad.widgets.worker_static import WorkerStatic
from contextlib import asynccontextmanager
from toad.widgets.message_divider import MessageDivider, MessageClock
from toad.widgets.message_notifications import MessageNotifications


class ThreadLink(CoreEventReceiver, Static, can_focus=True):
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
            self.publish_core(SelectHistoricalIdentity(self.target, self.history_source))
            return
        self.publish_core(
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

    def get_clipboard_text(self) -> str:
        return self.message.body


class IRCMessageText(WorkerStatic):
    """One wrapping, linked sender/destination/message block beside the time."""

    def action_open_target(self, target: str):
        self.query_ancestor(IRCMessage).action_open_target(target)

    def action_open_url(self, url: str):
        self.app.open_url(url)

    @asynccontextmanager
    async def preparation_publication(self, *, layout: bool):
        from toad.mounted_message_history import MountedMessageHistory

        history = (next((owner for owner in self.ancestors
                         if isinstance(owner, MountedMessageHistory)), None)
                   if layout else None)
        if history is None:
            async with super().preparation_publication(layout=layout):
                yield
        else:
            # Prepared text changes this body's extent, not the page's row
            # membership. Borrow the window's original reader without acquiring
            # page trimming/selection protection or fencing unrelated rows.
            window = history.window
            anchor = window.reader_anchor(self)
            async with window.preserve_history(anchor, root=self):
                yield
            window.check_follow()


class WireMarkdownMessage(CoreEventReceiver, ConversationBlock, VerticalGroup):
    """One original wire envelope; concrete bodies own only their rendering."""

    CACHE_SUBTREE_GEOMETRY = True
    DEFAULT_CLASSES = "block"
    BINDINGS = [
        ("enter", "open_sender", "Open sender"),
        ("shift+enter", "open_destination", "Open destination"),
    ]
    def __init__(self, message: Message, *, direction: str = "Inbound"):
        super().__init__()
        self.message = message
        # Composition acquires these native resources. Recomposition replaces
        # them; the row never borrows a retired body from a selector cache.
        self.body = None
        self.notifications = None
        self.direction = (
            f"History · {message.source.original_root} · @{message.sender} incarnation {message.sender_created_at}"
            if isinstance(message, HistoricalMessage) else direction
        )

    def compose(self) -> ComposeResult:
        yield MessageDivider(self.direction, clock=MessageClock.recorded(self.message.timestamp))
        yield from self.compose_body()
        self.notifications = MessageNotifications()
        yield self.notifications

    def compose_body(self) -> ComposeResult:
        from toad.widgets.agent_response import AgentResponse

        source = self.message.source.key if isinstance(self.message, HistoricalMessage) else None
        with HorizontalGroup():
            yield ThreadLink(self.message.sender, source)
            yield Static(" → ", markup=False, expand=False)
            yield ThreadLink(self.message.target, source)
        self.body = AgentResponse(self.message.body, show_divider=False)
        yield self.body
        if self.message.mentions:
            with HorizontalGroup():
                yield Static("Mentioned: ", expand=False)
                for target in dict.fromkeys(mention.thread for mention in self.message.mentions):
                    yield ThreadLink(target, source)

    def read_ack_widget(self) -> Widget | None:
        """Only the rendered message body can authorize a read."""
        return self.body if self.body is not None and self.body.is_attached else None

    @property
    def native_extent_ready(self) -> bool:
        """Paging borrows the body's real extent, not its loading placeholder."""
        return self.body is not None and self.body.is_attached and self.body.body_ready

    def action_open_target(self, target: str):
        if isinstance(self.message, HistoricalMessage) and not target.startswith("#"):
            self.publish_core(SelectHistoricalIdentity(target, self.message.source.key))
            return
        self.publish_core(
            SelectTarget(linked_target(target))
        )

    def action_open_sender(self):
        self.action_open_target(self.message.sender)

    def action_open_destination(self):
        self.action_open_target(self.message.target)

    def get_clipboard_text(self) -> str:
        return self.message.body


class IRCMessage(WireMarkdownMessage, can_focus=True):
    DEFAULT_CLASSES = ""
    DEFAULT_CSS = """
    IRCMessage {
        width: 1fr; height: auto; margin: 0; padding: 0;
        IRCMessageText { width: 1fr; height: auto; text-wrap: wrap; }
    }
    """

    def compose_body(self) -> ComposeResult:
        self.body = IRCMessageText(IRCMessageSource(self.message))
        yield self.body

    def read_ack_widget(self) -> Widget | None:
        """Only the text block can authorize a read, never its divider."""
        body = self.body
        return body if body is not None and body.is_attached and body.paint_ready else None

    @property
    def native_extent_ready(self) -> bool:
        return self.body is not None and self.body.is_attached and self.body.preparation_complete

    def get_clipboard_text(self) -> str:
        return f"{self.message.sender} → {self.message.target}: {self.message.body}"
