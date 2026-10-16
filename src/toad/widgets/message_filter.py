"""One semantic filter for native live blocks and saved transcript fragments."""

from __future__ import annotations

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
    @classmethod
    @abstractmethod
    def admits(cls, selected: frozenset[type[MessageCategory]]) -> bool: ...

    @classmethod
    @abstractmethod
    def observe(cls, boundary) -> bool: ...


class SelectableCategory(MessageCategory):
    label: str

    @classmethod
    def admits(cls, selected: frozenset[type[MessageCategory]]) -> bool:
        return cls in selected


class UnrestrictedCategory(MessageCategory):
    """A source container delegates filtering to the messages it draws."""

    @classmethod
    def admits(cls, selected: frozenset[type[MessageCategory]]) -> bool:
        return True

    @classmethod
    def observe(cls, boundary) -> bool:
        return False


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


class UserCategory(FromPerson, SelectableCategory):
    label = "User messages"


class AgentCategory(FromAgent, SelectableCategory):
    label = "Agent messages"


class InboundCategory(FromPerson, SelectableCategory):
    label = "Messages in"


class OutboundCategory(FromAgent, SelectableCategory):
    label = "Messages out"


class ThinkingCategory(AgentWork, SelectableCategory):
    label = "Thinking"


class ToolCategory(AgentWork, SelectableCategory):
    label = "Tool calls"


class OtherCategory(SelectableCategory):
    label = "Other / notices"

    @classmethod
    def observe(cls, boundary) -> bool:
        return False


def all_categories() -> frozenset[type[MessageCategory]]:
    return frozenset(MessageCategory.members_with(SelectableCategory))


class CategorizedBlock:
    """Derive native block eligibility from its declaring category and container."""

    @property
    def message_category(self) -> type[MessageCategory]:
        return OtherCategory

    @property
    def display_allowed(self) -> bool:
        return super().display_allowed and (
            not isinstance(self.parent, CategorizedMount)
            or self.message_category.admits(self.parent.selected_categories)
        )


class CategorizedMount:
    """Own native category admission and invalidate its child view once."""

    selected_categories: frozenset[type[MessageCategory]]

    def mount(self, *widgets, **kwargs):
        from toad.block_navigation import require_blocks

        mounted = super().mount(*require_blocks(widgets), **kwargs)
        # Registration is synchronous; preserve source order before mount tasks run.
        self.sort_children(key=lambda block: block.conversation_order)
        return mounted

    def categories_changed(self, previous, selected) -> None:
        if any(block.message_category.admits(previous) != block.message_category.admits(selected)
               for block in self.children):
            self.refresh_display()


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

