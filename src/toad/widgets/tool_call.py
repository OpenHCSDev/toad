from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import ToolCategory
from typing import Iterable

from textual import on
from textual import events
from textual.app import ComposeResult
from textual import getters

from textual.content import Content
from textual.reactive import var
from textual.css.query import NoMatches
from textual import containers
from textual.widgets import Static

from toad.app import ToadApp
from toad.tool_output import ToolOutput
from toad.widgets.tool_content import ToolCallDiff
from acp import schema as protocol
from toad.acp.tool_calls import tool_status
from toad.menus import MenuItem
from toad.pill import pill
from toad.widgets.message_filter import CategorizedBlock, MessageCategory
from toad.widgets.committed_presentation import SnapshotPresentation
from toad.layout import trim_trailing_margin
from textual.layout import WidgetPlacement

class ToolContent(containers.VerticalGroup):
    def process_layout(self, placements: list[WidgetPlacement]) -> list[WidgetPlacement]:
        return trim_trailing_margin(placements)


class ToolCallHeader(Static):
    ALLOW_SELECT = False
    DEFAULT_CSS = """
    ToolCallHeader {
        width: auto;
        max-width: 1fr;
        &:hover {
            background: $panel;
        }
    }
    """


class ToolCall(ConversationBlock, SnapshotPresentation, CategorizedBlock, containers.VerticalGroup):
    DEFAULT_CSS = """
    ToolCall {
        # margin: 0 0 0 0 !important;
        margin: 0 0 0 1 !important;

        width: 1fr;
        layout: vertical;
        height: auto;

        .icon {
            width: auto;
            margin-right: 1;
        }
        #tool-content {
            display: none;
        }
        &.-has-content #tool-content {
            margin: 1 1 1 0;
            DiffView {
                margin: 0 1 1 0;
            }

            Markdown {
                layout: stream;
                padding: 0;
                margin: 0 0 0 0;
            }
        }
        &.-expanded {
            #tool-content {
                display: block;
            }
            ToolCallHeader {
                text-wrap: wrap;
                text-overflow: fold;
            }
        }

        ToolCallHeader {
            color: $text-secondary;
            pointer: pointer;
            width: auto;
            max-width: 1fr;
            margin: 0 1 0 0;
            text-wrap: nowrap;
            text-overflow: ellipsis;
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
    tool_call: var[protocol.ToolCall | None] = var(None)

    def __init__(
        self,
        tool_call: protocol.ToolCall,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.set_reactive(ToolCall.tool_call, tool_call)
        super().__init__(id=id, classes=classes)
        self.output = ToolOutput(self)
        self._manual_expansion: bool | None = None
        self._auto_expanded = False

    async def update_tool_call(self, tool_call: protocol.ToolCall) -> None:
        """Update metadata in place; materialize output only when expanded.

        Args:
            tool_call: New Tool call data.
        """
        self.tool_call = tool_call
        self.output.replace(tool_call)
        self._update_metadata()
        header = self.query_one(ToolCallHeader)
        content = self.tool_call_header_content
        if header.content != content:
            header.update(content)
        await self.output.sync()

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
        tool_id = self.tool_call.tool_call_id if self.tool_call else None
        if isinstance(tool_id, str):
            conversation.remember_tool_expansion(tool_id, expanded)

    def is_block_expanded(self) -> bool:
        return self.expanded

    def compose(self) -> ComposeResult:
        assert self.tool_call is not None
        self.output.replace(self.tool_call)
        self._update_metadata()
        yield ToolCallHeader(self.tool_call_header_content, markup=False).with_tooltip(
            "Expand to see full title"
        )
        yield ToolContent(id="tool-content")

    async def on_mount(self) -> None:
        from toad.widgets.conversation import Conversation

        self.watch(self.app, "theme", self.output.theme_changed, init=False)
        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            pass
        else:
            tool_id = self.tool_call.tool_call_id if self.tool_call else None
            if isinstance(tool_id, str):
                self._manual_expansion = conversation.tool_expansions.get(tool_id)
                if self._manual_expansion is not None:
                    self._auto_expanded = False
                    self.expanded = self._manual_expansion
        await self.output.sync()

    def _update_metadata(self) -> None:
        assert self.tool_call is not None
        self.set_class(tool_status(self.tool_call).failed, "-failed")
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
        from toad.widgets.conversation import Window

        if not self.is_attached or not self.screen.is_active:
            return False
        geometry = self.screen._compositor.visible_widgets.get(self)
        if geometry is None:
            return False
        try:
            window = self.query_ancestor(Window)
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
        status = tool_status(tool_call)
        if (status.completed and tool_call_expand.patch_preview
                and self.output.preview_fits()):
            self._auto_expanded = True
            self.expanded = True
            return
        self.expanded = tool_call_expand.should_expand(status)
        self._auto_expanded = self.expanded

    @property
    def tool_call_header_content(self) -> Content:
        tool_call = self.tool_call
        assert tool_call is not None
        title = tool_call.title
        status = tool_status(tool_call)

        expand_icon: Content = Content()
        if self.has_content:
            expand_icon = Content.from_markup(
                "[$text-secondary]▼ " if self.expanded else "[$text-secondary]▶ "
            )
        else:
            expand_icon = Content.from_markup(
                "[$text-secondary 30%]▼ "
                if self.expanded
                else "[$text-secondary 30%]▶ "
            )

        header = Content.assemble(expand_icon, "🔧 ", title)

        header += status.header(self)
        return header

    async def watch_expanded(self) -> None:
        await self.output.sync()
        try:
            self.query_one(ToolCallHeader).update(self.tool_call_header_content)
        except NoMatches:
            pass
        from toad.widgets.conversation import Conversation

        try:
            conversation = self.query_ancestor(Conversation)
        except NoMatches:
            pass
        else:
            self.call_after_refresh(conversation.cursor.update_follow)

    @on(events.Click, "ToolCallHeader")
    def on_click_tool_call_header(self, event: events.Click) -> None:
        event.stop()
        if self.has_content:
            self.set_expanded(not self.expanded)
        else:
            self.app.bell()
