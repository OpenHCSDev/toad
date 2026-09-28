"""One semantic filter for native live blocks and saved transcript fragments."""

from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily

from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    TranscriptEvent,
    UserTranscript,
    AssistantTranscript,
    NoticeTranscript,
    SentTranscript,
    ThinkingTranscript,
    ToolTranscript,
)


class MessageCategory(DeclaredFamily, affix="Category"):
    label: str

    @classmethod
    @abstractmethod
    def observe(cls, boundary) -> bool: ...


class FromPerson:
    @classmethod
    def observe(cls, boundary) -> bool:
        boundary.reset()
        return False


class FromAgent:
    @classmethod
    def observe(cls, boundary) -> bool:
        boundary._pending = False
        return False


class AgentWork:
    @classmethod
    def observe(cls, boundary) -> bool:
        show = boundary._pending
        boundary._pending = False
        return show


class RoutedMessage:
    """Messages retained while the native transcript supplies ordinary blocks."""


class UserCategory(FromPerson, MessageCategory):
    label = "User messages"


class AgentCategory(FromAgent, MessageCategory):
    label = "Agent messages"


class InboundCategory(RoutedMessage, FromPerson, MessageCategory):
    label = "Messages in"


class OutboundCategory(RoutedMessage, FromAgent, MessageCategory):
    label = "Messages out"


class ThinkingCategory(AgentWork, MessageCategory):
    label = "Thinking"


class ToolCategory(AgentWork, MessageCategory):
    label = "Tool calls"


class OtherCategory(MessageCategory):
    label = "Other / notices"

    @classmethod
    def observe(cls, boundary) -> bool:
        return False


def all_categories() -> frozenset[type[MessageCategory]]:
    return frozenset(MessageCategory.members_with(MessageCategory))


class CategorizedBlock:
    """Nominal widget mixin for the declared presentation category.

    Textual widgets own a custom metaclass, so a separate ABCMeta would be
    inconsistent with their inheritance. Concrete blocks implement this member.
    """

    @property
    def message_category(self) -> type[MessageCategory] | None:
        """None reserves a container for its saved-history projection."""
        raise NotImplementedError


class TranscriptCategoryConsumer(MroDispatch):
    def __init__(self):
        self.category = OtherCategory

    @handles(UserTranscript)
    def user(self, event: UserTranscript):
        self.category = InboundCategory if event.routed else UserCategory

    @handles(AssistantTranscript)
    def assistant(self, event: AssistantTranscript):
        self.category = OutboundCategory if event.routed else AgentCategory

    @handles(NoticeTranscript)
    def notice(self, event: NoticeTranscript):
        self.category = OutboundCategory if event.routed else OtherCategory

    @handles(SentTranscript)
    def sent(self, event: SentTranscript):
        self.category = OutboundCategory

    @handles(ThinkingTranscript)
    def thinking(self, event: ThinkingTranscript):
        self.category = ThinkingCategory

    @handles(ToolTranscript)
    def tool(self, event: ToolTranscript):
        self.category = ToolCategory


def event_category(event: TranscriptEvent) -> type[MessageCategory]:
    consumer = TranscriptCategoryConsumer()
    consumer.dispatch_sync(event)
    return consumer.category


def keep_events(
    events: tuple[TranscriptEvent, ...], selected: frozenset[type[MessageCategory]]
) -> bool:
    """A fragment remains if any of its semantic events is selected."""
    return any(event_category(event) in selected for event in events)


def block_category(widget) -> type[MessageCategory] | None:
    """Ask the native block; uncategorized controls belong to Other."""
    return (
        widget.message_category
        if isinstance(widget, CategorizedBlock)
        else OtherCategory
    )


def apply_block_filter(widget, selected: frozenset[type[MessageCategory]]) -> None:
    """Change only this semantic owner, preserving its authored display rules."""
    category = block_category(widget)
    hidden = category is not None and category not in selected
    marker = "-category-hidden"
    if widget.has_class(marker) != hidden:
        # Keep the marker available for custom styling. Ordinary filtering is a
        # model-owned display constraint, not a request to rematch subtree CSS.
        update_styles = widget.is_attached and widget.app.stylesheet.references_class(
            marker
        )
        widget.set_class(hidden, marker, update=update_styles)
    widget.set_display_constraint("message-category", not hidden)


def keep_live_block(widget) -> bool:
    category = block_category(widget)
    return (
        category is None
        or issubclass(category, RoutedMessage)
        or widget.has_class("-error")
        or widget.has_class("-error-log-link")
    )
