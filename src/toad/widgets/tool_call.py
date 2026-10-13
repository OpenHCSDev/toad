from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import ToolCategory
from typing import Iterable
from contextlib import asynccontextmanager

from textual.app import ComposeResult
from textual import getters

from textual.reactive import var
from textual.css.query import NoMatches
from textual import containers
from textual.widget import Widget

from toad.app import ToadApp
from toad.tool_output import ToolOutput, ToolOutputPart
from toad.widgets.tool_content import ToolCallDiff
from toad.acp.status import ToolCallStatus
from toad.line_blocks import ToggleDetails
from toad.menus import MenuItem
from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import SnapshotPresentation
from toad.layout import trim_trailing_margin
from textual.layout import WidgetPlacement
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.await_complete import AwaitComplete

from toad.widgets.agent_activity import AgentActivityPresentation
from toad.widgets.line_markdown import LineMarkdown
from toad.widgets.message_divider import SingleLineBlock


class ToolContent(containers.VerticalGroup):
    """The decoded output parts of one tool call."""

    def __init__(self, *args, **kwargs):
        self._mounted_parts: tuple[ToolOutputPart, ...] | None = None
        super().__init__(*args, **kwargs)

    @property
    def output(self) -> ToolOutput:
        return self.query_ancestor(ToolCall).output

    def on_unmount(self) -> None:
        self._mounted_parts = None

    def sync(self) -> AwaitComplete:
        if self._mounted_parts == self.output.displayed_parts:
            return AwaitComplete()
        return AwaitComplete(self._mount_parts())

    async def recompose(self) -> None:
        if not self.is_attached:
            return
        async with self.lock:
            self._mounted_parts = None
            await self._mount_parts()

    async def _mount_parts(self) -> None:
        output = self.output
        parts = output.displayed_parts
        if self._mounted_parts == parts:
            return
        with self.app.batch_update():
            retained = len(parts) == len(self._mounted_parts or ()) == len(self.children) == 1
            if not retained or not parts[0].update_widget(self._mounted_parts[0], self.children[0]):
                await self.remove_children()
                await self.mount_all(widget for part in parts for widget in part.compose(output.view))
            self._mounted_parts = parts

    @height_dependency(INDEPENDENT_HEIGHT)
    def process_layout(self, placements: list[WidgetPlacement]) -> list[WidgetPlacement]:
        return trim_trailing_margin(placements)


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

    def action_open(self, link) -> None:
        if not isinstance(link, ToggleDetails):
            return
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
            DiffView {
                margin: 0 1 1 0;
            }

            Markdown {
                layout: stream;
                padding: 0;
                margin: 0;
            }
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

    def update_tool_call(self, tool_call: ToolCallStatus) -> AwaitComplete:
        """Update metadata in place; materialize output only when expanded.

        Args:
            tool_call: New Tool call data.
        """
        self.tool_call = tool_call
        self.output.replace(tool_call.call)
        self._update_metadata()
        self.query_one(ToolCallHeader).update_block(self.activity_rows[0])
        self.query_one("#tool-title", LineMarkdown).update(self.tool_call.call.title or "Tool")
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
        if expanded:
            for diff in self.query(ToolCallDiff):
                diff.publish_if_ready()
        from toad.widgets.conversation import Conversation

        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            return
        tool_id = self.tool_call.call.tool_call_id if self.tool_call else None
        if isinstance(tool_id, str):
            conversation.remember_tool_expansion(tool_id, expanded)

    def is_block_expanded(self) -> bool:
        return self.expanded

    def compose(self) -> ComposeResult:
        assert self.tool_call is not None
        self._update_metadata()
        yield ToolCallHeader(self.activity_rows[0]).with_tooltip("Expand to see full title")
        yield LineMarkdown(self.tool_call.call.title or "Tool", markdown=False, id="tool-title")
        yield ToolContent(id="tool-content")

    def on_mount(self) -> None:
        from toad.widgets.conversation import Conversation

        self.watch(self.app, "theme", self.output.theme_changed, init=False)
        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            pass
        else:
            tool_id = self.tool_call.call.tool_call_id if self.tool_call else None
            if isinstance(tool_id, str):
                self._manual_expansion = conversation.tool_expansions.get(tool_id)
                if self._manual_expansion is not None:
                    self._auto_expanded = False
                    self.expanded = self._manual_expansion
        self.output.sync()

    def _update_metadata(self) -> None:
        assert self.tool_call is not None
        self.set_class(self.tool_call.failed, "-failed")
        self.has_content = self.output.has_content
        self.check_expand()

    def notify_style_update(self) -> None:
        super().notify_style_update()
        self.output.theme_changed()

    async def on_show(self) -> None:
        self.output.hydrate_if_visible()

    def hydrate_if_visible(self) -> None:
        self.output.hydrate_if_visible()

    def on_unmount(self) -> None:
        self.output.retire()

    def _visible_in_window(self) -> bool:
        from toad.widgets.history_anchor import HistoryWindow

        if not self.is_attached or not self.screen.is_active:
            return False
        geometry = self.screen._compositor.visible_widgets.get(self)
        if geometry is None:
            return False
        try:
            window = self.query_ancestor(HistoryWindow)
        except NoMatches:
            return True
        region, _clip = geometry
        return region.overlaps(window.content_region)

    @property
    def content_open(self) -> bool:
        return self.is_mounted and self.is_attached and self.expanded

    @property
    def content_in_view(self) -> bool:
        return self.content_open and self._visible_in_window()

    @property
    def content_presentable(self) -> bool:
        if not self.expanded:
            return False
        return not self._auto_expanded or self._visible_in_window()

    def check_expand(self) -> None:
        """Check if the tool call should auto-expand."""
        if self._manual_expansion is not None:
            return
        if not self.has_content:
            return
        tool_call = self.tool_call
        assert tool_call is not None
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
        assert self.tool_call is not None
        return AgentActivityPresentation.tool_has_details(self.tool_call, self.has_content)

    @property
    def activity_rows(self):
        assert self.tool_call is not None
        return AgentActivityPresentation.tool(
            self.tool_call, has_details=self.has_details, details_open=self.expanded
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
