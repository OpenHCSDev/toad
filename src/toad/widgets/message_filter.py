"""One semantic filter for native live blocks and saved transcript fragments."""

from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily

from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    TranscriptEvent,
    UserTranscript,
    IncomingTranscript,
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


class UserCategory(FromPerson, MessageCategory):
    label = "User messages"


class AgentCategory(FromAgent, MessageCategory):
    label = "Agent messages"


class InboundCategory(FromPerson, MessageCategory):
    label = "Messages in"


class OutboundCategory(FromAgent, MessageCategory):
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
        self.category = UserCategory

    @handles(IncomingTranscript)
    def incoming(self, event: IncomingTranscript):
        self.category = InboundCategory

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
    widget.set_display_constraint("message-category", not hidden)
