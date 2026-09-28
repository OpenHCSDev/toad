"""One semantic filter for native live blocks and saved transcript fragments."""

from enum import StrEnum

from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    TranscriptEvent, UserTranscript, AssistantTranscript, NoticeTranscript,
    SentTranscript, ThinkingTranscript, ToolTranscript,
)


class MessageCategory(StrEnum):
    USER = "user"
    AGENT = "agent"
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    THINKING = "thinking"
    TOOL = "tool"
    OTHER = "other"


MESSAGE_CATEGORIES = tuple(MessageCategory)
ALL_CATEGORIES = frozenset(MESSAGE_CATEGORIES)
IN_OUT_CATEGORIES = frozenset((MessageCategory.INBOUND, MessageCategory.OUTBOUND))

MESSAGE_LABELS = {
    MessageCategory.USER: "User messages",
    MessageCategory.AGENT: "Agent messages",
    MessageCategory.INBOUND: "Messages in",
    MessageCategory.OUTBOUND: "Messages out",
    MessageCategory.THINKING: "Thinking",
    MessageCategory.TOOL: "Tool calls",
    MessageCategory.OTHER: "Other / notices",
}


class CategorizedBlock:
    """Nominal widget mixin for the declared presentation category.

    Textual widgets own a custom metaclass, so a separate ABCMeta would be
    incompatible with their inheritance. Concrete blocks implement this member.
    """

    @property
    def message_category(self) -> MessageCategory | None:
        """None reserves a container for its saved-history projection."""
        raise NotImplementedError


class TranscriptCategoryConsumer(MroDispatch):
    def __init__(self):
        self.category = MessageCategory.OTHER

    @handles(UserTranscript)
    def user(self, event: UserTranscript):
        self.category = MessageCategory.INBOUND if event.routed else MessageCategory.USER

    @handles(AssistantTranscript)
    def assistant(self, event: AssistantTranscript):
        self.category = MessageCategory.OUTBOUND if event.routed else MessageCategory.AGENT

    @handles(NoticeTranscript)
    def notice(self, event: NoticeTranscript):
        self.category = MessageCategory.OUTBOUND if event.routed else MessageCategory.OTHER

    @handles(SentTranscript)
    def sent(self, event: SentTranscript):
        self.category = MessageCategory.OUTBOUND

    @handles(ThinkingTranscript)
    def thinking(self, event: ThinkingTranscript):
        self.category = MessageCategory.THINKING

    @handles(ToolTranscript)
    def tool(self, event: ToolTranscript):
        self.category = MessageCategory.TOOL


def event_category(event: TranscriptEvent) -> MessageCategory:
    consumer = TranscriptCategoryConsumer()
    consumer.dispatch_sync(event)
    return consumer.category


def keep_events(events: tuple[TranscriptEvent, ...], selected: frozenset[MessageCategory]) -> bool:
    """A fragment remains if any of its semantic events is selected."""
    return any(event_category(event) in selected for event in events)


def block_category(widget) -> MessageCategory | None:
    """Ask the native block; uncategorized controls belong to Other."""
    return widget.message_category if isinstance(widget, CategorizedBlock) else MessageCategory.OTHER


def apply_block_filter(widget, selected: frozenset[MessageCategory]) -> None:
    """Change only this semantic owner, preserving its authored display rules."""
    category = block_category(widget)
    hidden = category is not None and category not in selected
    marker = "-category-hidden"
    if widget.has_class(marker) != hidden:
        # Keep the marker available for custom styling. Ordinary filtering is a
        # model-owned display constraint, not a request to rematch subtree CSS.
        update_styles = (
            widget.is_attached and widget.app.stylesheet.references_class(marker)
        )
        widget.set_class(hidden, marker, update=update_styles)
    widget.set_display_constraint("message-category", not hidden)


def keep_live_block(widget) -> bool:
    category = block_category(widget)
    return (category is None or category in IN_OUT_CATEGORIES
            or widget.has_class("-error") or widget.has_class("-error-log-link"))
