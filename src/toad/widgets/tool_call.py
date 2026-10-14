from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import ToolCategory
from typing import Iterable

from textual.app import ComposeResult
from textual.await_complete import AwaitComplete
from textual import getters

from textual.reactive import var
from textual.css.query import NoMatches
from textual import containers
from textual.geometry import Size
from textual.selection import Selection
from textual.strip import Strip
from textual.widget import Widget
from textual.worker import Worker

from toad.app import ToadApp
from toad.tool_output import ToolOutput, ToolOutputPart
from agent_comms.mro_dispatch import handles
from toad.acp.status import ToolCallStatus
from toad.line_blocks import LineBlock, ToggleDetails, ToolOutputRole
from toad.menus import MenuItem
from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import SnapshotPresentation
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency

from toad.widgets.agent_activity import AgentActivityPresentation
from toad.widgets.line_markdown import LineMarkdown
from toad.widgets.message_divider import SingleLineBlock
from toad.widgets.transcript_lines import (
    LinkedRows, Lines, PlainLines, PreparedLines, TranscriptLinesRenderTask, link_place,
)


class ToolContent(LinkedRows, Widget):
    """One live details widget painting the parts' canonical line blocks."""

    DEFAULT_CSS = "ToolContent { height: auto; }"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.blocks: tuple[LineBlock, ...] = ()
        self._styled: PreparedLines | None = None
        self._plain: PlainLines | None = None
        self._width = 0
        self._link_place = link_place()
        self._render_worker: Worker[None] | None = None

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self._theme_changed)

    def _theme_changed(self, _theme) -> None:
        self._styled = None
        self._plain = None
        self._request_render()
        self.refresh(layout=True)

    def update(self, blocks: tuple[LineBlock, ...]) -> None:
        if blocks == self.blocks:
            return
        previous_height = self._lines(self._width).height if self._width else 0
        self.blocks = blocks
        self._styled = None
        self._plain = None
        self._request_render()
        current_height = self._lines(self._width).height if self._width else 0
        self.refresh(layout=previous_height != current_height)

    def _lines(self, width: int) -> Lines:
        styled = self._styled
        if styled is not None and styled.width == width:
            return styled
        if self._plain is None or self._plain.width != width:
            self._plain = PlainLines(width, self.app.colours.line_theme, self.blocks)
        return self._plain

    def _request_render(self) -> None:
        if self._width and self.is_attached:
            self._render_worker = self.run_worker(
                self._render(), group="tool-details", exclusive=True
            )

    async def _render(self) -> None:
        blocks, width, theme = self.blocks, self._width, self.app.colours.line_theme
        lines = await self.app.render_processes.submit(
            TranscriptLinesRenderTask(blocks, width, theme)
        )
        if (
            self.is_attached
            and blocks == self.blocks
            and width == self._width
            and theme is self.app.colours.line_theme
        ):
            previous_height = self._lines(width).height
            self._styled = lines
            self.refresh(layout=previous_height != lines.height)

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        if width != self._width:
            self._width = width
            self._styled = None
            self._plain = None
            self.call_later(self._request_render)
        return self._lines(width).height

    def render_line(self, y: int) -> Strip:
        width = self._width
        strips = self._lines(width).strips_at(self._link_place) if width else ()
        if y >= len(strips):
            return self.blank_row(width)
        return self.on_background(strips[y])

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        text = "\n".join(block.selection_text for block in self.blocks)
        return selection.extract(text), "\n"


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

    def update_tool_call(self, tool_call: ToolCallStatus) -> AwaitComplete:
        """Update metadata in place; materialize output only when expanded.

        Args:
            tool_call: New Tool call data.
        """
        self.tool_call = tool_call
        self.output.replace(tool_call.call)
        self._update_metadata()
        self.query_one(ToolCallHeader).update_block(self.activity_rows[0])
        self.query_one("#tool-title", LineMarkdown).update(self.current_status.title)
        return self.output.sync()

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

    def hydrate_if_visible(self) -> None:
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
