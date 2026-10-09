"""A readable, inspectable disclosure for context identified by the executing owner."""

from toad.widgets.message_filter import OtherCategory
from toad.block_navigation import ConversationBlock

import asyncio
from typing import TYPE_CHECKING

from textual.widgets import Collapsible

from toad.widgets.agent_response import AgentResponse
from toad.coordination_context_format import format_coordination_context, literal_context

if TYPE_CHECKING:
    from toad.widgets.transcript_fragments import ContextTranscriptFragment



class ContextDisclosure(ConversationBlock, Collapsible):
    """The displayed payload and disclosure state belong to this widget."""

    def __init__(self, content: str, *, title: str) -> None:
        super().__init__(title=title, collapsed=True)
        self.content = content

    def get_clipboard_text(self) -> str:
        return self.content

    def can_expand(self) -> bool:
        return self.collapsed

    def is_block_expanded(self) -> bool:
        return not self.collapsed

    def expand_block(self) -> None:
        self.collapsed = False

    def collapse_block(self) -> None:
        self.collapsed = True


class OriginalCoordinationContext(ContextDisclosure):
    def __init__(self, content: str, *, source: "ContextTranscriptFragment") -> None:
        super().__init__(content, title="Original payload")
        self._body: AgentResponse | None = None
        self.source = source

    async def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self and self._body is None:
            self._body = AgentResponse(literal_context(self.content), show_divider=False,
                                       category=OtherCategory, prepared_content=self.source.original_content)
            await self.query_one(Collapsible.Contents).mount(self._body)

    def retain_transcript_source(self, fragment):
        if self._body is not None:
            self.source.original_content = self._body.retain_sources()


class CoordinationContext(ContextDisclosure):
    def __init__(self, content: str, *, source: "ContextTranscriptFragment") -> None:
        super().__init__(content, title="Agent coordination context")
        self._body: AgentResponse | None = None
        self.source = source
        self._original: OriginalCoordinationContext | None = None
        self._preparing = False

    async def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is not self or self._body is not None or self._preparing:
            return
        self._preparing = True
        try:
            # Neither JSON formatting nor Markdown preparation belongs in the
            # hidden transcript's paint path. Keep one lazy result per disclosure.
            if self.source.formatted is None:
                self.source.formatted = await asyncio.to_thread(format_coordination_context, self.content)
            if not self.is_attached or self.collapsed:
                return
            self._body = AgentResponse(self.source.formatted, show_divider=False, category=OtherCategory,
                                       prepared_content=self.source.prepared_content)
            contents = self.query_one(Collapsible.Contents)
            await contents.mount(self._body)
            if self.source.formatted != self.content:
                self._original = OriginalCoordinationContext(self.content, source=self.source)
                await contents.mount(self._original)
        finally:
            self._preparing = False

    def retain_transcript_source(self, fragment):
        if self._body is not None:
            self.source.prepared_content = self._body.retain_sources()
        if self._original is not None:
            self._original.retain_transcript_source(fragment)
