"""An inspectable disclosure for context identified by the executing owner."""

from textual.widgets import Collapsible

from toad.widgets.agent_response import AgentResponse


class CoordinationContext(Collapsible):
    def __init__(self, content: str) -> None:
        super().__init__(title="Agent coordination context", collapsed=True)
        self.content = content
        self._body: AgentResponse | None = None

    async def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is not self or self._body is not None:
            return
        # Hidden owner metadata can be large. Prepare its Markdown only when
        # requested, using the same paged renderer as an ordinary agent reply.
        self._body = AgentResponse(self.content, show_divider=False)
        await self.query_one(Collapsible.Contents).mount(self._body)

    def get_block_content(self, destination: str) -> str:
        return self.content

    def collapse_block(self) -> None:
        self.collapsed = True

    def expand_block(self) -> None:
        self.collapsed = False
