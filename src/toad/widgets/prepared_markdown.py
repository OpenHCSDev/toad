"""Use the app-owned CPU pool for heavy conversation Markdown preparation."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import cast

from markdown_it import MarkdownIt
from markdown_it.token import Token

from rich.segment import Segment
from rich.style import Style as RichStyle

from textual.content import Content
from textual.app import ComposeResult
from textual._measurement import NATIVE_WIDGET_HEIGHT, height_dependency
from textual.css.styles import RulesMap
from textual.geometry import Offset, Size
from textual.selection import Selection
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, Visual
from textual.worker import WorkerCancelled
from textual.await_complete import AwaitComplete
from textual.widget import Widget
from textual.widgets import Label
from textual.widgets._label import LabelVariant
from textual.widgets._markdown import Markdown, MarkdownBlock

from toad.app import ToadApp
from toad.conversation_markdown import ConversationCodeFence, ConversationMarkdown, _ThreadLocalPathParser
from toad.markdown_preparation import FenceKey, PreparedFence
from toad.render_tasks import MarkdownRenderTask
from toad.widgets.transcript_fragments import RenderBudget
from toad.widgets.viewport_body import MeasuredViewportBody


class PreparedConversationMarkdown(MeasuredViewportBody, ConversationMarkdown):
    def native_body_ready(self) -> bool:
        return super().native_body_ready() and not self.loading

    def _measured_virtual_size_requires_layout(self) -> bool:
        # Markdown extent comes from its arranged blocks, not a separately
        # authored virtual document. Committing that result must not feed it
        # back into the same ancestor measurements. Actual scrollbar changes
        # and content/stylesheet updates retain their ordinary invalidation.
        return False

    def __init__(
        self, markdown: str | None = None, *, name: str | None = None,
        id: str | None = None, classes: str | None = None,
        parser_factory: Callable[[], MarkdownIt] | None = None, open_links: bool = False,
    ) -> None:
        self._prepared_fences: dict[FenceKey, PreparedFence] = {}
        factory = self._make_parser if parser_factory is None else parser_factory
        super().__init__(markdown, name=name, id=id, classes=classes,
                         parser_factory=factory, open_links=open_links)

    def reconstructible_children(self) -> tuple[Widget, ...]:
        """Native resources rebuilt from this document's original source."""
        return tuple(child for child in self.children if isinstance(child, MarkdownBlock))

    def retire_body_resources(self) -> None:
        """Release reconstructible preparation with the native retirement."""
        self._prepared_fences.clear()

    async def materialize_native_body(self) -> None:
        await self._update_body_source(self.source)

    def update(self, markdown: str) -> AwaitComplete:
        return self.publish_body(partial(self._update_body_source, markdown))

    def append(self, markdown: str) -> AwaitComplete:
        return self.publish_body(partial(self._append_body_source, markdown))

    def _update_body_source(self, markdown: str) -> AwaitComplete:
        return super().update(markdown)

    def _append_body_source(self, markdown: str) -> AwaitComplete:
        return super().append(markdown)

    async def prepare_body(self) -> None:
        # Results live only in PreparationRuntime's bounded cache. Fresh file
        # links and widget construction remain at the foreground delivery.
        await self.app.render_processes.submit(MarkdownRenderTask(
            self.source, self.app.native_ansi_color, self.app.current_theme.dark,
        ))

    def on_unmount(self) -> None:
        self._prepared_fences.clear()

    async def _parse_tokens(
        self, parser: MarkdownIt | _ThreadLocalPathParser, markdown: str, *, use_thread: bool,
    ) -> list[Token] | None:
        # Custom parser factories retain their native semantics. This process
        # function implements the declaration-owned conversation/path parser.
        if not isinstance(parser, _ThreadLocalPathParser):
            return await super()._parse_tokens(parser, markdown, use_thread=use_thread)
        if not isinstance(self.app, ToadApp):
            return (await asyncio.to_thread(parser.parse, markdown)
                    if use_thread else parser.parse(markdown))

        parent = self.parent
        # Runway and delivery use the same pure preparation key. Filesystem
        # links are resolved only in each independent delivered token resource,
        # after highlighting; they never become reusable renderer inputs.
        while not self._closing and self.is_attached and not self._pruning:
            theme = (self.app.native_ansi_color, self.app.current_theme.dark)
            request = self.app.render_processes.submit(MarkdownRenderTask(markdown, *theme))
            worker = self.run_worker(request, group="markdown-preparation", exit_on_error=False)
            try:
                prepared = await worker.wait()
            except WorkerCancelled:
                if self._closing or self._pruning or not self.is_attached:
                    return None
                raise asyncio.CancelledError
            if (self._closing or not self.is_attached or self._pruning
                    or self.parent is not parent):
                return None
            tokens = await asyncio.to_thread(parser.resolve_tokens, prepared.tokens)
            if (self._closing or not self.is_attached or self._pruning
                    or self.parent is not parent):
                return None
            if theme != (self.app.native_ansi_color, self.app.current_theme.dark):
                continue
            self._prepared_fences = prepared.fences
            return tokens
        return None

    def _get_prepared_fence(self, code: str, language: str, ansi: bool, dark: bool) -> Content | None:
        prepared = self._prepared_fences.get((code, language, ansi, dark))
        return None if prepared is None else prepared.content

    def get_block_class(self, block_name: str) -> type[MarkdownBlock]:
        if block_name in {"fence", "code_block"}:
            return PreparedCodeFence
        return super().get_block_class(block_name)


class _FenceRow(Visual):
    def __init__(self, content: Content, y: int) -> None:
        self.content, self.y = content, y

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return self.content.get_optimal_width(rules, container_width)

    def get_height(self, rules: RulesMap, width: int) -> int:
        return self.content.get_height(rules, width)

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions,
    ) -> list[Strip]:
        selection = options.selection
        if selection is not None:
            start, end = selection
            selection = Selection(
                None if start is None else Offset(start.x, start.y - self.y),
                None if end is None else Offset(end.x, end.y - self.y),
            )
            options = replace(options, selection=selection)
        strips = self.content.render_strips(width, height, style, options)
        result: list[Strip] = []
        for strip in strips:
            segments: list[Segment] = []
            for text, rich_style, control in strip:
                if rich_style is not None and rich_style._meta is not None:
                    metadata = rich_style.meta
                    if "offset" in metadata:
                        x, y = cast(tuple[int, int | None], metadata["offset"])
                        metadata["offset"] = (x, None if y is None else y + self.y)
                        rich_style = rich_style + RichStyle.from_meta(metadata)
                segments.append(Segment(text, rich_style, control))
            result.append(Strip(segments, strip.cell_length))
        return result


class PreparedCodeLabel(Label):
    def __init__(
        self, content: Content, lines: tuple[Content, ...], *, variant: LabelVariant | None = None,
        expand: bool = False, shrink: bool = False, markup: bool = True,
        name: str | None = None, id: str | None = None, classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        self._code_content, self._code_lines = content, lines
        self._code_has_tabs = "\t" in content.plain
        super().__init__(content, variant=variant, expand=expand, shrink=shrink, markup=markup,
                         name=name, id=id, classes=classes, disabled=disabled)

    def set_code(self, content: Content, lines: tuple[Content, ...]) -> None:
        if self.content is content:
            return
        layout = not isinstance(self.content, Content) or self.content.plain != content.plain
        self._code_content, self._code_lines = content, lines
        self._code_has_tabs = "\t" in content.plain
        self.update(content, layout=layout)

    @height_dependency(NATIVE_WIDGET_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        if (width > 0 and self._render() is self._code_content and not self._code_has_tabs
                and self._code_content.get_optimal_width(self.styles.get_rules(), width) <= width):
            # The worker already split this code and measured its widest row.
            # Every row fits at this width, so reformatting the complete fence
            # during first mount or tab reflow cannot change its line count.
            return len(self._code_lines)
        return super().get_content_height(container, viewport, width)

    def render_line(self, y: int) -> Strip:
        content = self._render()
        if (content is not self._code_content or self.styles.content_align != ("left", "top")
                or content.get_optimal_width(self.styles.get_rules(), self.size.width) > self.size.width):
            return super().render_line(y)
        if not 0 <= y < len(self._code_lines):
            return Strip.blank(self.size.width, self.visual_style.rich_style)
        return Visual.to_strips(self, _FenceRow(self._code_lines[y], y), self.size.width,
                               1, self.visual_style)[0]


class PreparedCodeFence(ConversationCodeFence):
    def __init__(self, markdown: Markdown, token: Token, code: str) -> None:
        self._rows_content: Content | None = None
        self._rows: tuple[Content, ...] = ()
        super().__init__(markdown, token, code)

    def _code_rows(self) -> tuple[Content, ...]:
        content = self._highlighted_code
        if self._rows_content is not content:
            key = (self.code, self.lexer, self.app.native_ansi_color, self.app.current_theme.dark)
            document = self._markdown
            assert isinstance(document, PreparedConversationMarkdown)
            prepared = document._prepared_fences.get(key)
            self._rows = (prepared.lines if prepared is not None and prepared.content is content
                          else tuple(content.split("\n", allow_blank=True)))
            self._rows_content = content
        return self._rows

    def set_content(self, content: Content) -> None:
        self._content = content
        label = self.query_one_optional("#code-content", PreparedCodeLabel)
        if label is not None:
            label.set_code(content, self._code_rows())

    def compose(self) -> ComposeResult:
        yield PreparedCodeLabel(self._highlighted_code, self._code_rows(), id="code-content", expand=True)
