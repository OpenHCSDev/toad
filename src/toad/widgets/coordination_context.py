"""A readable, inspectable disclosure for context identified by the executing owner."""

import asyncio

from textual.widgets import Collapsible

from toad.widgets.agent_response import AgentResponse
from toad.widgets.message_filter import MessageCategory
from toad.coordination_context_format import format_coordination_context, literal_context


class OriginalCoordinationContext(Collapsible):
    def __init__(self, content: str) -> None:
        super().__init__(title="Original payload", collapsed=True)
        self.content = content
        self._body: AgentResponse | None = None

    async def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self and self._body is None:
            self._body = AgentResponse(literal_context(self.content), show_divider=False,
                                       category=MessageCategory.OTHER)
            await self.query_one(Collapsible.Contents).mount(self._body)

    def get_block_content(self, destination: str) -> str:
        return self.content


class CoordinationContext(Collapsible):
    def __init__(self, content: str) -> None:
        super().__init__(title="Agent coordination context", collapsed=True)
        self.content = content
        self._body: AgentResponse | None = None
        self._formatted: str | None = None
        self._preparing = False

    async def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is not self or self._body is not None or self._preparing:
            return
        self._preparing = True
        try:
            # Neither JSON formatting nor Markdown preparation belongs in the
            # hidden transcript's paint path. Keep one lazy result per disclosure.
            if self._formatted is None:
                self._formatted = await asyncio.to_thread(format_coordination_context, self.content)
            if not self.is_attached or self.collapsed:
                return
            self._body = AgentResponse(self._formatted, show_divider=False, category=MessageCategory.OTHER)
            contents = self.query_one(Collapsible.Contents)
            await contents.mount(self._body)
            if self._formatted != self.content:
                await contents.mount(OriginalCoordinationContext(self.content))
        finally:
            self._preparing = False

    def get_block_content(self, destination: str) -> str:
        return self.content

    def collapse_block(self) -> None:
        self.collapsed = True

    def expand_block(self) -> None:
        self.collapsed = False
