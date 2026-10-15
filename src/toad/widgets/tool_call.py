from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import ToolCategory
from typing import Iterable

from textual.app import ComposeResult
from textual.await_complete import AwaitComplete
from textual import getters

from textual.reactive import var
from textual.css.query import NoMatches
from textual import containers
from textual.widget import Widget

from toad.app import ToadApp
from toad.tool_output import ToolOutput, ToolOutputPart
from agent_comms.mro_dispatch import handles
from toad.acp.status import ToolCallStatus
from toad.line_blocks import ToggleDetails, ToolOutputRole
from toad.menus import MenuItem
from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import SnapshotPresentation

from toad.widgets.agent_activity import AgentActivityPresentation
from toad.widgets.line_markdown import LineMarkdown
from toad.widgets.message_divider import SingleLineBlock
from toad.widgets.tool_content import ToolContent




class ToolCallHeader(SingleLineBlock):
    ALLOW_SELECT = False
    DEFAULT_CSS = """
    ToolCallHeader {
        width: 1fr;
        &:hover {
            background: $panel;
        }
    }
    """

    @handles(ToggleDetails)
    def toggle_details(self, link: ToggleDetails) -> None:
        tool = self.query_ancestor(ToolCall)
        if tool.has_details:
            tool.set_expanded(not tool.expanded)
        else:
            self.app.bell()


class ToolCall(ConversationBlock, SnapshotPresentation, CategorizedBlock, containers.VerticalGroup):
    DEFAULT_CSS = """
    ToolCall {
        margin: 0 !important;
        width: 1fr;
        layout: vertical;
        height: auto;

        #tool-title, #tool-content {
            display: none;
        }
        &.-has-content #tool-content {
            margin: 0 1 1 0;
        }
        &.-expanded {
            #tool-title, #tool-content {
                display: block;
            }
        }

        ToolCallHeader {
            pointer: pointer;
        }
    }
    """

    DEFAULT_CLASSES = "block"

    @property
    def message_category(self) -> type[MessageCategory]:
        return ToolCategory

    app = getters.app(ToadApp)
    has_content: var[bool] = var(False, toggle_class="-has-content")
    expanded: var[bool] = var(False, toggle_class="-expanded")
    tool_call: var[ToolCallStatus | None] = var(None)

    def __init__(
        self,
        tool_call: ToolCallStatus,
        *,
        id: str | None = None,
        classes: str | None = None,
        output_parts: tuple[ToolOutputPart, ...] | None = None,
    ) -> None:
        self.set_reactive(ToolCall.tool_call, tool_call)
        super().__init__(id=id, classes=classes)
        self.output = ToolOutput(self)
        self.output.replace(tool_call.call, parts=output_parts)
        self._manual_expansion: bool | None = None
        self._auto_expanded = False

    @property
    def current_status(self) -> ToolCallStatus:
        status = self.tool_call
        assert status
        return status

    def update_tool_call(self, tool_call: ToolCallStatus, *, output_parts=None) -> AwaitComplete:
        """Update metadata in place; materialize output only when expanded.

        Args:
            tool_call: New Tool call data.
        """
        self.tool_call = tool_call
        self.output.replace(tool_call.call, parts=output_parts)
        self._update_metadata()
        self.query_one(ToolCallHeader).update_block(self.activity_rows[0])
        self.query_one("#tool-title", LineMarkdown).update(self.current_status.title)
        return self.output.sync()

    @classmethod
    async def present(cls, conversation, event):
        if event.scope != conversation.agent.tools.scope:
            return
        status = event.tool_call
        status.activity(conversation.turns, conversation.output, status.title)
        parts = await ToolOutput.prepare_messages(conversation, status, event.scope)
        if event.scope != conversation.agent.tools.scope:
            return
        try:
            tool = conversation.contents.get_child_by_id(event.tool_id, cls)
        except NoMatches:
            await conversation.post(cls(status, id=event.tool_id, output_parts=parts), new_block=True)
        else:
            tool.update_tool_call(status, output_parts=parts)

    def get_block_menu(self) -> Iterable[MenuItem]:
        if self.expanded:
            yield MenuItem("Collapse", "block.collapse", "x")
        else:
            yield MenuItem("Expand", "block.expand", "x")

    def action_collapse(self) -> None:
        self.set_expanded(False)

    def action_expand(self) -> None:
        self.set_expanded(True)

    def can_expand(self) -> bool:
        return not self.expanded

    def expand_block(self) -> None:
        self.set_expanded(True)

    def collapse_block(self) -> None:
        self.set_expanded(False)

    def set_expanded(self, expanded: bool) -> None:
        """Record explicit presentation intent separately from ACP status updates."""
        self._manual_expansion = expanded
        self._auto_expanded = False
        self.expanded = expanded
        from toad.widgets.conversation import Conversation

        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            return
        tool_id = self.current_status.call.tool_call_id
        if isinstance(tool_id, str):
            conversation.remember_tool_expansion(tool_id, expanded)

    def is_block_expanded(self) -> bool:
        return self.expanded

    def compose(self) -> ComposeResult:
        self._update_metadata()
        yield ToolCallHeader(self.activity_rows[0]).with_tooltip("Expand to see full title")
        yield LineMarkdown(self.current_status.title, role=ToolOutputRole,
                           markdown=False, id="tool-title")
        yield ToolContent(id="tool-content")

    def on_mount(self) -> None:
        from toad.widgets.conversation import Conversation

        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            pass
        else:
            tool_id = self.current_status.call.tool_call_id
            if isinstance(tool_id, str):
                self._manual_expansion = conversation.tool_expansions.get(tool_id)
                if self._manual_expansion is not None:
                    self._auto_expanded = False
                    self.expanded = self._manual_expansion
        self.output.sync()

    def _update_metadata(self) -> None:
        self.set_class(self.current_status.failed, "-failed")
        self.has_content = self.output.has_content
        self.check_expand()

    def check_expand(self) -> None:
        """Check if the tool call should auto-expand."""
        if self._manual_expansion is not None:
            return
        if not self.has_content:
            return
        tool_call = self.current_status
        if self.output.suppress_auto_expansion:
            # Don't auto expand reads, as it can generate a lot of noise
            return
        tool_call_expand = self.app.settings.tools.expand
        status = tool_call
        if (status.completed and tool_call_expand.patch_preview
                and self.output.preview_fits()):
            self._auto_expanded = True
            self.expanded = True
            return
        self.expanded = tool_call_expand.should_expand(status)
        self._auto_expanded = self.expanded

    @property
    def has_details(self) -> bool:
        return AgentActivityPresentation.tool_has_details(self.current_status, self.has_content)

    @property
    def activity_rows(self):
        return AgentActivityPresentation.tool(
            self.current_status, has_details=self.has_details, details_open=self.expanded
        )

    def watch_expanded(self) -> None:
        self.output.sync()
        try:
            self.query_one(ToolCallHeader).update_block(self.activity_rows[0])
        except NoMatches:
            pass
        from toad.widgets.conversation import Conversation

        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            pass
        else:
            self.call_after_refresh(conversation.cursor.refresh)
