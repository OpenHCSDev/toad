from toad.block_navigation import CategorizedBlock, ConversationBlock

from agent_comms.ui_model.message_category import ToolCategory
from typing import Iterable

from textual.app import ComposeResult
from textual.await_complete import AwaitComplete

from textual import events
from textual.reactive import var
from textual.css.native import DeclaresTheme, Keyword, NativeDeclaration, Variable
from textual.css.query import NoMatches
from textual.css.styles import Styles
from textual import containers
from ui_theme.scheme import PanelColour

from toad.tool_output import ToolOutput, ToolOutputPart
from metaclass_registry.mro_dispatch import handles
from toad.acp.status import ToolCallStatus
from toad.line_blocks import Body, ToggleDetails, ToolOutputRole
from toad.block_content import CollapseCommand, ExpandCommand
from toad.menus import MenuCommand
from agent_comms.ui_model.message_category import MessageCategory
from toad.widgets.committed_presentation import SnapshotPresentation
from toad.commit_claims import CAPTURED_CLAIM, CapturedClaim, ToolOutputClaim

from toad.widgets.agent_activity import AgentActivityPresentation
from toad.widgets.line_markdown import LineMarkdown
from toad.widgets.message_divider import ConversationLineBlock
from toad.widgets.tool_content import ToolContent
from toad.app_node import ToadNode
from toad.native_style import PointerCursor, RightMargin
from toad.widgets.conversation import Conversation
from textual import on


class HeaderPointer(DeclaresTheme):
    """Where the pointer is relative to a tool's header row; each place declares its paint."""

    native_theme: tuple[NativeDeclaration, ...] = (
        NativeDeclaration.of(Styles.background, Keyword("transparent")),
    )


class HoveredHeader(HeaderPointer):
    native_theme = (NativeDeclaration.of(Styles.background, Variable(PanelColour.name)),)


class ToolCallHeader(PointerCursor, ConversationLineBlock):
    ALLOW_SELECT = False
    pointer_place: type[HeaderPointer] = HeaderPointer


    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        return (*super().native_declarations(), *self.pointer_place.declared_theme())

    @on(events.Enter)
    def on_enter(self, event: events.Enter) -> None:
        self.pointer_place = HoveredHeader
        self.app.update_styles(self)

    @on(events.Leave)
    def on_leave(self, event: events.Leave) -> None:
        self.pointer_place = HeaderPointer
        self.app.update_styles(self)

    @handles(ToggleDetails)
    def toggle_details(self, link: ToggleDetails) -> None:
        tool = self.query_ancestor(ToolCall)
        if tool.has_details:
            tool.set_expanded(not tool.expanded)
        else:
            self.app.bell()


class ToolTitle(LineMarkdown):
    """The full title, shown with the details while the call is expanded."""


class ToolCallContent(RightMargin, ToolContent):
    """The call's details, shown while it is expanded."""



class ToolCall(ConversationBlock, SnapshotPresentation, CategorizedBlock, containers.VerticalGroup, ToadNode):
    @property
    def message_category(self) -> type[MessageCategory]:
        return ToolCategory

    has_content: var[bool] = var(False)
    expanded: var[bool] = var(False)
    tool_call: var[ToolCallStatus | None] = var(None)

    def __init__(
        self,
        tool_call: ToolCallStatus,
        *,
        output_parts: tuple[ToolOutputPart, ...] | None = None,
        binding=None,
        request=None,
        source_claim: CapturedClaim = CAPTURED_CLAIM,
    ) -> None:
        self.set_reactive(ToolCall.tool_call, tool_call)
        self.source_claim = source_claim
        self.binding = binding
        self.request = request
        super().__init__()
        self.output = ToolOutput(self)
        self.output.replace(tool_call.call, parts=output_parts)
        self._manual_expansion: bool | None = None
        self._auto_expanded = False

    @property
    def current_status(self) -> ToolCallStatus:
        status = self.tool_call
        assert status
        return status

    @property
    def commit_claim(self):
        return ToolOutputClaim(frozenset(message.message.reference for part in self.output.parts
                                        for message in part.standalone_messages),
                               source=self.committed_source)

    def update_tool_call(self, tool_call: ToolCallStatus, *, output_parts=None) -> AwaitComplete:
        """Update metadata in place; materialize output only when expanded.

        Args:
            tool_call: New Tool call data.
        """
        self.tool_call = tool_call
        self.output.replace(tool_call.call, parts=output_parts)
        self._update_metadata()
        self.query_one(ToolCallHeader).update_block(self.activity_rows[0])
        self.query_one(ToolTitle).update(self.current_status.title)
        return self.output.sync()

    def get_block_menu(self) -> Iterable[MenuCommand]:
        if self.expanded:
            yield CollapseCommand(self)
        else:
            yield ExpandCommand(self)

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
        title = ToolTitle(self.current_status.title, role=ToolOutputRole, body=Body)
        details = ToolCallContent()
        title.display = details.display = self.expanded
        yield title
        yield details

    @on(events.Mount)
    def on_mount(self) -> None:

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
        if tool_call_expand.expands_preview(status, self.output.preview_fits):
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
            self.query_one(ToolTitle).display = self.query_one(ToolCallContent).display = self.expanded
        except NoMatches:
            pass

        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            pass
        else:
            self.call_after_refresh(conversation.cursor.refresh)
