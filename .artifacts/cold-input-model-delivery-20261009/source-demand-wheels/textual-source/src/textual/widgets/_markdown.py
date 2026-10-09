from __future__ import annotations

import asyncio
import re
import weakref
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePath
from types import MethodType
from typing import TYPE_CHECKING, AsyncIterator, Callable, Iterable, Optional, Sequence
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.token import Token
from rich.text import Text
from typing_extensions import TypeAlias

from textual._slug import TrackedSlugs, slug_for_tcss_id
from textual.app import ComposeResult
from textual.await_complete import AwaitComplete
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content, Span
from textual.css.query import NoMatches
from textual.events import Mount
from textual.highlight import highlight
from textual.layout import Layout
from textual.layouts.grid import GridLayout
from textual.message import Message
from textual.reactive import reactive, var
from textual.style import Style
from textual.widget import Widget
from textual.widgets import Static, Tree
from textual.widgets._label import Label

if TYPE_CHECKING:
    from textual.document._markdown import MarkdownDocument, MarkdownSourceBlock
    from textual.document._paint import DocumentPaint

TableOfContentsType: TypeAlias = "list[tuple[int, str, str | None]]"
"""Information about the table of contents of a markdown document.

The triples encode the level, the label, and the optional block id of each heading.
"""


class MarkdownStream:
    """An object to manage streaming markdown.

    This will accumulate markdown fragments if they can't be rendered fast enough.

    This object is typically created by the [Markdown.get_stream][textual.widgets.Markdown.get_stream] method.

    """

    def __init__(self, markdown_widget: Markdown) -> None:
        """
        Args:
            markdown_widget: Markdown widget to update.
        """
        self.markdown_widget = markdown_widget
        self._task: asyncio.Task | None = None
        self._new_markup = asyncio.Event()
        self._pending: list[str] = []
        self._stopped = False

    def start(self) -> None:
        """Start the updater running in the background.

        No need to call this, if the object was created by [Markdown.get_stream][textual.widgets.Markdown.get_stream].

        """
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the stream and await its finish."""
        self._stopped = True
        self._new_markup.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # Caller cancellation must not abandon the stream's append drain.
                await asyncio.shield(task)
                raise
            finally:
                if task.done() and self._task is task:
                    self._task = None

    async def write(self, markdown_fragment: str) -> None:
        """Append or enqueue a markdown fragment.

        Args:
            markdown_fragment: A string to append at the end of the document.
        """
        if self._stopped:
            raise RuntimeError("Can't write to the stream after it has stopped.")
        if not markdown_fragment:
            # Nothing to do for empty strings.
            return
        # Append the new fragment, and set an event to tell the _run loop to wake up
        self._pending.append(markdown_fragment)
        self._new_markup.set()
        # Allow the task to wake up and actually display the new markdown
        await asyncio.sleep(0)

    async def _run(self) -> None:
        """Run a task to append markdown fragments when available."""
        try:
            while not self._stopped or self._pending:
                await self._new_markup.wait()
                new_markdown = "".join(self._pending)
                self._pending.clear()
                self._new_markup.clear()
                if new_markdown:
                    await asyncio.shield(self.markdown_widget.append(new_markdown))
        except asyncio.CancelledError:
            # Task has been cancelled, add any outstanding markdown
            pass

        new_markdown = "".join(self._pending)
        if new_markdown:
            await self.markdown_widget.append(new_markdown)


@dataclass(frozen=True)
class MarkdownLocation:
    """One decoded filesystem destination and its separate document anchor."""

    path: Path
    anchor: str = ""

    def resolve(self, current: MarkdownLocation) -> MarkdownLocation:
        path = (
            current.path
            if self.path == Path(".") and self.anchor
            else current.path.parent / self.path
        )
        return MarkdownLocation(path.absolute(), self.anchor)

    async def load(self, document: Markdown) -> None:
        data = await asyncio.get_running_loop().run_in_executor(
            None, partial(self.path.read_text, encoding="utf-8")
        )
        await document.update(data)
        if self.anchor:
            document.goto_anchor(self.anchor)


class Navigator:
    """Manages a stack of paths like a browser."""

    def __init__(self) -> None:
        self.stack: list[MarkdownLocation] = []
        self.index = 0

    @property
    def location(self) -> MarkdownLocation:
        """The current location.

        Returns:
            The original filesystem destination and its document anchor.
        """
        if not self.stack:
            return MarkdownLocation(Path("."))
        return self.stack[self.index]

    @property
    def start(self) -> bool:
        """Is the current location at the start of the stack?"""
        return self.index == 0

    @property
    def end(self) -> bool:
        """Is the current location at the end of the stack?"""
        return self.index >= len(self.stack) - 1

    def go(self, path: str | PurePath | MarkdownLocation) -> MarkdownLocation:
        """Go to a new document.

        Args:
            path: Path to new document.

        Returns:
            New location.
        """
        location = Markdown.sanitize_location(path)
        new_path = location.resolve(self.location)
        self.stack = self.stack[: self.index + 1]
        self.stack.append(new_path)
        self.index = len(self.stack) - 1
        return new_path

    def back(self) -> bool:
        """Go back in the stack.

        Returns:
            True if the location changed, otherwise False.
        """
        if self.index:
            self.index -= 1
            return True
        return False

    def forward(self) -> bool:
        """Go forward in the stack.

        Returns:
            True if the location changed, otherwise False.
        """
        if self.index < len(self.stack) - 1:
            self.index += 1
            return True
        return False


class MarkdownBlock(Static):
    """The base class for a Markdown Element."""

    COMPONENT_CLASSES = {"em", "strong", "s", "code_inline"}
    """
    These component classes target standard inline markdown styles.
    Changing these will potentially break the standard markdown formatting.

    | Class | Description |
    | :- | :- |
    | `code_inline` | Target text that is styled as inline code. |
    | `em` | Target text that is emphasized inline. |
    | `s` | Target text that is styled inline with strikethrough. |
    | `strong` | Target text that is styled inline with strong. |
    """

    DEFAULT_CSS = """
    MarkdownBlock {
        width: 1fr;
        height: auto;
    }
    """

    def __init__(
        self,
        markdown: Markdown,
        token: Token,
        source_range: tuple[int, int] | None = None,
        *args,
        source_block: MarkdownSourceBlock | None = None,
        **kwargs,
    ) -> None:
        self._markdown_ref = weakref.ref(markdown)
        """A reference to the Markdown document that contains this block."""
        self._content: Content = Content()
        self._token: Token = token
        self._blocks: list[MarkdownBlock] = []
        self._inline_token: Token | None = None
        self._source_block = source_block
        self.source_range: tuple[int, int] = (
            source_block.source_range if source_block is not None else
            source_range or (
                (token.map[0], token.map[1]) if token.map is not None else (0, 0)
            )
        )

        super().__init__(
            *args,
            name=token.type,
            classes=f"level-{token.level}",
            expand=True,
            **kwargs,
        )

    def _is_block_type(self, declaration: type[MarkdownBlock]) -> bool:
        return isinstance(self, declaration)

    @property
    def source_block(self) -> MarkdownSourceBlock | None:
        """The actual acquired member, while this scene still owns its source.

        A normal update or append revokes the detached-source relation even
        when text or line ranges happen to agree. No descendant or placement
        projection can recreate it.
        """
        source = self._source_block
        return (
            source if source is not None
            and self._markdown.is_current_document(source.document) else None
        )

    @classmethod
    async def from_source(
        cls, markdown: Markdown, source: MarkdownSourceBlock
    ) -> MarkdownBlock:
        """Construct genuine controls from this original acquired grammar member.

        Custom constructors receive their original grammar arguments and must
        accept the source binding, or declare their own scene factory. Native
        composition and callbacks still run on the real scene widgets.
        """
        if source.declaration is not cls:
            raise TypeError("Scene declaration differs from its acquired grammar member")
        await asyncio.sleep(0)
        block = cls(
            markdown, source._token, *source._arguments, source_block=source
        )
        if source._inline_token is not None:
            block.build_from_token(source._inline_token)
        block._blocks = [
            await child.declaration.from_source(markdown, child)
            for child in source._blocks
        ]
        if source.id is not None:
            block.id = source.id
        return block

    def heading_id(self) -> str:
        return self.make_heading_id(self._content, id(self))

    @staticmethod
    def make_heading_id(content: Content, identity: object) -> str:
        """Original slug plus the actual source/scene lifetime identity."""
        return f"heading-{slug_for_tcss_id(content.plain)}-{identity}"

    @property
    def _markdown(self) -> Markdown:
        """Resolve the weak ref to _markdown"""
        markdown = self._markdown_ref()
        assert markdown is not None
        return markdown

    @property
    def select_container(self) -> Widget:
        return self.query_ancestor(Markdown)

    @property
    def source(self) -> str | None:
        """The source of this block if known, otherwise `None`."""
        source = self.source_block
        if source is not None:
            return source.source_text()
        if self.source_range is None:
            return None
        return self.source_text(self._markdown.source, self.source_range)

    @staticmethod
    def source_text(source: str, source_range: tuple[int, int]) -> str:
        start, end = source_range
        return "".join(source.splitlines(keepends=True)[start:end])

    def _copy_context(self, block: MarkdownBlock) -> None:
        """Copy the context from another block."""
        self._token = block._token
        self._source_block = block._source_block

    def compose(self) -> ComposeResult:
        yield from self._blocks
        self._blocks.clear()

    @classmethod
    def document_node(cls, block, *, compose=compose):
        """Use native content/composition; custom behavior supplies this producer.

        The acquired source node is a different lifetime from a scene widget.
        Custom constructors, renderers, measurements and disclosure must declare
        their own data-only preparation rather than run on a counterfeit widget.
        """
        cls._require_native_document()
        cls._require_document_methods({"compose": compose})
        return cls.native_document_node(block)

    @classmethod
    def native_document_node(cls, block):
        """Shared native composition for explicit prepared-content declarations."""
        return block.node(children=[child.prepare() for child in block._blocks])

    @classmethod
    def document_declarations(cls):
        """Actual style declarations constructed by this document producer."""
        return (cls,)

    def set_content(self, content: Content) -> None:
        self._content = content
        self.update(content)

    async def _update_from_block(self, block: MarkdownBlock) -> None:
        await self.remove()
        await self._markdown.mount(block)

    async def action_link(self, href: str) -> None:
        """Called on link click."""
        self._markdown.action_link(href)

    def build_from_token(self, token: Token) -> None:
        """Build inline block content from its source token.

        Args:
            token: The token from which this block is built.
        """
        self._inline_token = token
        source = self._source_block
        if source is not None and token is not source._inline_token:
            self._source_block = source = None
        content = (
            self._markdown._get_token_content(token, block=self)
            if source is None else source._content
        )
        self.set_content(content)

    @staticmethod
    def _token_to_content(token: Token) -> Content:
        """Convert an inline token to Textual Content.

        Args:
            token: A markdown token.

        Returns:
            Content instance.
        """

        if token.children is None:
            return Content("")

        tokens: list[str] = []
        spans: list[Span] = []
        style_stack: list[tuple[Style | str, int]] = []
        position: int = 0

        def add_content(text: str) -> None:
            """Add text to the tokens list, and advance the position.

            Args:
                text: Text to add.

            """
            nonlocal position
            tokens.append(text)
            position += len(text)

        def add_style(style: Style | str) -> None:
            """Add a style to the stack.

            Args:
                style: A style as Style instance or string.
            """
            style_stack.append((style, position))

        position = 0

        def close_tag() -> None:
            style, start = style_stack.pop()
            spans.append(Span(start, position, style))

        for child in token.children:
            child_type = child.type
            if child_type == "text":
                add_content(re.sub(r"\s+", " ", child.content))
            if child_type == "hardbreak":
                add_content("\n")
            if child_type == "softbreak":
                add_content(" ")
            elif child_type == "code_inline":
                add_style(".code_inline")
                add_content(child.content)
                close_tag()
            elif child_type == "em_open":
                add_style(".em")
            elif child_type == "strong_open":
                add_style(".strong")
            elif child_type == "s_open":
                add_style(".s")
            elif child_type == "link_open":
                href = child.attrs.get("href", "")
                action = f"link({href!r})"
                add_style(Style.from_meta({"@click": action}))
            elif child_type == "image":
                href = child.attrs.get("src", "")
                alt = child.attrs.get("alt", "")
                action = f"link({href!r})"
                add_style(Style.from_meta({"@click": action}))
                add_content("🖼  ")
                if alt:
                    add_content(f"({alt})")
                if child.children is not None:
                    for grandchild in child.children:
                        add_content(grandchild.content)
                close_tag()

            elif child_type.endswith("_close"):
                close_tag()

        content = Content("".join(tokens), spans=spans)
        return content

    @classmethod
    def _require_native_document(
        cls,
        *,
        constructor=__init__,
        render=Static.render,
        width=Widget.get_content_width,
        height=Widget.get_content_height,
        box=Widget._get_box_model,
        pre_layout=Widget.pre_layout,
        process_layout=Widget.process_layout,
        selection=Widget.get_selection,
        build_from_token=build_from_token,
        set_content=set_content,
        content=_token_to_content,
        visual=Static.visual,
        container=Widget.is_container,
        rendering=Widget._render,
        empty=Widget.is_empty,
        pseudo_classes=Widget.get_pseudo_classes,
    ):
        cls._require_document_methods(
            {
                "__init__": constructor,
                "render": render,
                "get_content_width": width,
                "get_content_height": height,
                "_get_box_model": box,
                "pre_layout": pre_layout,
                "process_layout": process_layout,
                "get_selection": selection,
                "build_from_token": build_from_token,
                "set_content": set_content,
                "_token_to_content": content.__func__,
                "visual": visual,
                "is_container": container,
                "_render": rendering,
                "is_empty": empty,
                "get_pseudo_classes": pseudo_classes,
            }
        )


class MarkdownHeader(MarkdownBlock):
    """Base class for a Markdown header."""

    LEVEL = 0

    @classmethod
    def make_heading_entry(cls, content: Content, block_id: str | None):
        """Heading wording belongs to the block's actual acquired Content."""
        return cls.LEVEL, content.plain, block_id

    def table_of_contents_entry(self):
        return self.make_heading_entry(self._content, self.id)

    DEFAULT_CSS = """
    MarkdownHeader {
        color: $text;
        margin: 2 0 1 0;

    }
    """


class MarkdownH1(MarkdownHeader):
    """An H1 Markdown header."""

    LEVEL = 1

    DEFAULT_CSS = """
    MarkdownH1 {
        content-align: center middle;
        color: $markdown-h1-color;
        background: $markdown-h1-background;
        text-style: $markdown-h1-text-style;
    }
    """


class MarkdownH2(MarkdownHeader):
    """An H2 Markdown header."""

    LEVEL = 2

    DEFAULT_CSS = """
    MarkdownH2 {
        color: $markdown-h2-color;
        background: $markdown-h2-background;
        text-style: $markdown-h2-text-style;
    }
    """


class MarkdownH3(MarkdownHeader):
    """An H3 Markdown header."""

    LEVEL = 3

    DEFAULT_CSS = """
    MarkdownH3 {
        color: $markdown-h3-color;
        background: $markdown-h3-background;
        text-style: $markdown-h3-text-style;
        margin: 1 0;
        width: auto;
    }
    """


class MarkdownH4(MarkdownHeader):
    """An H4 Markdown header."""

    LEVEL = 4

    DEFAULT_CSS = """
    MarkdownH4 {
        color: $markdown-h4-color;
        background: $markdown-h4-background;
        text-style: $markdown-h4-text-style;
        margin: 1 0;
    }
    """


class MarkdownH5(MarkdownHeader):
    """An H5 Markdown header."""

    LEVEL = 5

    DEFAULT_CSS = """
    MarkdownH5 {
        color: $markdown-h5-color;
        background: $markdown-h5-background;
        text-style: $markdown-h5-text-style;
        margin: 1 0;
    }
    """


class MarkdownH6(MarkdownHeader):
    """An H6 Markdown header."""

    LEVEL = 6

    DEFAULT_CSS = """
    MarkdownH6 {
        color: $markdown-h6-color;
        background: $markdown-h6-background;
        text-style: $markdown-h6-text-style;
        margin: 1 0;
    }
    """


class MarkdownHorizontalRule(MarkdownBlock):
    """A horizontal rule."""

    DEFAULT_CSS = """
    MarkdownHorizontalRule {
        border-bottom: solid $secondary;
        height: 1;
        padding-top: 1;
        margin-bottom: 1;
    }
    """


class MarkdownParagraph(MarkdownBlock):
    """A paragraph Markdown block."""

    SCOPED_CSS = False
    DEFAULT_CSS = """
    Markdown > MarkdownParagraph {
         margin: 0 0 1 0;
    }
    """

    async def _update_from_block(self, block: MarkdownBlock):
        if isinstance(block, MarkdownParagraph):
            self.set_content(block._content)
            self._copy_context(block)
        else:
            await super()._update_from_block(block)


class MarkdownBlockQuote(MarkdownBlock):
    """A block quote Markdown block."""

    DEFAULT_CSS = """
    MarkdownBlockQuote {
        background: $boost;
        border-left: outer $text-primary 50%;
        margin: 1 0;
        padding: 0 1;
    }
    MarkdownBlockQuote:light {
        border-left: outer $text-secondary;
    }
    MarkdownBlockQuote > BlockQuote {
        margin-left: 2;
        margin-top: 1;
    }
    """


class MarkdownList(MarkdownBlock):
    DEFAULT_CSS = """

    MarkdownList {
        width: 1fr;
    }

    MarkdownList MarkdownList {
        margin: 0;
        padding-top: 0;
    }
    """

    @staticmethod
    def compose_rows(rows, make_bullet, make_column, make_row):
        for symbol, blocks in rows:
            yield make_row(make_bullet(symbol), make_column(blocks))

    @classmethod
    def document_declarations(cls):
        return (cls, Horizontal, Vertical, MarkdownBullet)


class MarkdownBulletList(MarkdownList):
    """A Bullet list Markdown block."""

    DEFAULT_CSS = """
    MarkdownBulletList {
        margin: 0 0 1 0;
        padding: 0 0;
    }

    MarkdownBulletList Horizontal {
        height: auto;
        width: 1fr;
    }

    MarkdownBulletList Vertical {
        height: auto;
        width: 1fr;
    }
    """

    @staticmethod
    def list_rows(blocks):
        for block in blocks:
            if block._is_block_type(MarkdownListItem):
                yield block.bullet, block._blocks

    def compose(self) -> ComposeResult:
        yield from self.compose_rows(
            self.list_rows(self._blocks),
            MarkdownBullet.from_symbol,
            lambda blocks: Vertical(*blocks),
            Horizontal,
        )
        self._blocks.clear()

    @classmethod
    def document_node(cls, block, *, _compose=compose):
        cls._require_native_document()
        cls._require_document_methods({"compose": _compose})
        return block.list_node(cls.list_rows(block._blocks))


class MarkdownOrderedList(MarkdownList):
    """An ordered list Markdown block."""

    DEFAULT_CSS = """
    MarkdownOrderedList {
        margin: 0 0 1 0;
        padding: 0 0;
    }

    MarkdownOrderedList Horizontal {
        height: auto;
        width: 1fr;
    }

    MarkdownOrderedList Vertical {
        height: auto;
        width: 1fr;
    }
    """

    @staticmethod
    def list_rows(blocks):
        suffix = ". "
        start = 1
        if blocks and blocks[0]._is_block_type(MarkdownOrderedListItem):
            try:
                start = int(blocks[0].bullet)
            except ValueError:
                pass
        symbol_size = max(
            len(f"{number}{suffix}")
            for number, block in enumerate(blocks, start)
            if block._is_block_type(MarkdownListItem)
        )
        for number, block in enumerate(blocks, start):
            if block._is_block_type(MarkdownListItem):
                yield f"{number}{suffix}".rjust(symbol_size + 1), block._blocks

    def compose(self) -> ComposeResult:
        yield from self.compose_rows(
            self.list_rows(self._blocks),
            MarkdownBullet.from_symbol,
            lambda blocks: Vertical(*blocks),
            Horizontal,
        )
        self._blocks.clear()

    @classmethod
    def document_node(cls, block, *, _compose=compose):
        cls._require_native_document()
        cls._require_document_methods({"compose": _compose})
        return block.list_node(cls.list_rows(block._blocks))


class MarkdownTableCellContents(Static):
    """Widget for table cells.

    A shim over a Static which responds to links.
    """

    async def action_link(self, href: str) -> None:
        """Pass a link action on to the MarkdownTable parent."""
        self.query_ancestor(Markdown).action_link(href)


class MarkdownTableContent(Widget):
    """Renders a Markdown table."""

    DEFAULT_CSS = """
    MarkdownTableContent {
        width: 1fr;
        height: auto;
        layout: grid;
        grid-columns: auto;
        grid-rows: auto;
        grid-gutter: 1 1;

        & > .cell {
            margin: 0 0;
            height: auto;
            padding: 0 1;
            text-overflow: ellipsis;
        }
        & > .header {
            height: auto;
            margin: 0 0;
            padding: 0 1;
            color: $primary;
            text-overflow: ellipsis;
            content-align: left bottom;
        }
        keyline: thin $foreground 20%;
    }
    MarkdownTableContent > .markdown-table--header {
        text-style: bold;
    }
    """

    COMPONENT_CLASSES = {"markdown-table--header", "markdown-table--lines"}

    def __init__(self, headers: list[Content], rows: list[list[Content]]):
        self.headers = headers.copy()
        """List of header text."""
        self.rows = rows.copy()
        """The row contents."""
        super().__init__()
        self.shrink = True
        self.last_row = 0

    def pre_layout(self, layout: Layout) -> None:
        self.prepare_grid(
            layout, self.query_ancestor(MarkdownTable).styles.is_auto_width
        )

    @staticmethod
    def cells(headers, rows):
        for header in headers:
            yield header, "header", None, header, 0
        for row_index, row in enumerate(rows, 1):
            for cell_index, cell in enumerate(row, 1):
                yield (
                    cell,
                    f"row{row_index} cell",
                    f"cell{row_index}.{cell_index}",
                    cell.plain,
                    row_index,
                )

    @staticmethod
    def prepare_grid(layout: Layout, auto_width: bool) -> None:
        assert isinstance(layout, GridLayout)
        layout.auto_minimum = True
        layout.expand = not auto_width
        layout.shrink = True
        layout.stretch_height = True

    def compose(self) -> ComposeResult:
        for content, classes, name, tooltip, row in self.cells(self.headers, self.rows):
            yield MarkdownTableCellContents(
                content, classes=classes, name=name
            ).with_tooltip(tooltip)
            self.last_row = row

    def _update_content(self, headers: list[Content], rows: list[list[Content]]):
        """Update cell contents."""
        self.headers = headers
        self.rows = rows
        cells: list[Content] = [
            *self.headers,
            *[cell for row in self.rows for cell in row],
        ]
        for child, updated_cell in zip(self.query(MarkdownTableCellContents), cells):
            child.update(updated_cell, layout=False)

    async def _update_rows(self, updated_rows: list[list[Content]]) -> None:
        self.styles.grid_size_columns = len(self.headers)
        await self.query_children(f".cell.row{self.last_row}").remove()
        new_cells: list[Static] = []
        for row_index, row in enumerate(updated_rows, self.last_row):
            for cell in row:
                new_cells.append(
                    Static(
                        cell,
                        classes=f"row{row_index} cell",
                    ).with_tooltip(cell)
                )
                await asyncio.sleep(0)
        self.last_row = row_index
        await self.mount_all(new_cells)

    def on_mount(self) -> None:
        self.styles.grid_size_columns = len(self.headers)

    async def action_link(self, href: str) -> None:
        """Pass a link action on to the MarkdownTable parent."""
        if isinstance(self.parent, MarkdownTable):
            await self.parent.action_link(href)


class MarkdownTable(MarkdownBlock):
    """A Table markdown Block."""

    DEFAULT_CSS = """
    MarkdownTable {
        width: 1fr;
        margin-bottom: 1;
        &:light {
            background: white 30%;
        }
    }
    """

    def __init__(self, markdown: Markdown, token: Token, *args, **kwargs) -> None:
        super().__init__(markdown, token, *args, **kwargs)
        self._headers: list[Content] = []
        self._rows: list[list[Content]] = []

    def compose(self) -> ComposeResult:
        headers, rows = self._get_headers_and_rows()
        self._headers = headers
        self._rows = rows
        yield MarkdownTableContent(headers, rows)

    def _get_headers_and_rows(self) -> tuple[list[Content], list[list[Content]]]:
        return self.table_contents(self)

    @staticmethod
    def table_contents(source) -> tuple[list[Content], list[list[Content]]]:
        """Get list of headers, and list of rows.

        Returns:
            A tuple containing a list of headers, and a list of rows.
        """

        def flatten(block: MarkdownBlock) -> Iterable[MarkdownBlock]:
            for block in block._blocks:
                if block._blocks:
                    yield from flatten(block)
                yield block

        headers: list[Content] = []
        rows: list[list[Content]] = []
        for block in flatten(source):
            if block._is_block_type(MarkdownTH):
                headers.append(block._content)
            elif block._is_block_type(MarkdownTR):
                rows.append([])
            elif block._is_block_type(MarkdownTD):
                rows[-1].append(block._content)
        if rows and not rows[-1]:
            rows.pop()
        return headers, rows

    @classmethod
    def document_node(
        cls, block, *, _compose=compose, _contents=table_contents, constructor=__init__
    ):
        cls._require_native_document(constructor=constructor)
        cls._require_document_methods(
            {"compose": _compose, "table_contents": _contents.__func__}
        )
        return block.table_node(*cls.table_contents(block))

    @classmethod
    def document_declarations(cls):
        return (cls, MarkdownTableContent, MarkdownTableCellContents)

    async def _update_from_block(self, block: MarkdownBlock) -> None:
        """Special case to update a Markdown table.

        Args:
            block: Existing markdown block.
        """
        if isinstance(block, MarkdownTable):
            try:
                table_content = self.query_one(MarkdownTableContent)
            except NoMatches:
                pass
            else:
                if table_content.rows:
                    current_rows = self._rows
                    _new_headers, new_rows = block._get_headers_and_rows()
                    updated_rows = new_rows[len(current_rows) - 1 :]
                    self._rows = new_rows
                    await table_content._update_rows(updated_rows)
                    return
        await super()._update_from_block(block)


class MarkdownTBody(MarkdownBlock):
    """A table body Markdown block."""


class MarkdownTHead(MarkdownBlock):
    """A table head Markdown block."""


class MarkdownTR(MarkdownBlock):
    """A table row Markdown block."""


class MarkdownTH(MarkdownBlock):
    """A table header Markdown block."""


class MarkdownTD(MarkdownBlock):
    """A table data Markdown block."""


class MarkdownBullet(Widget):
    """A bullet widget."""

    DEFAULT_CSS = """
    MarkdownBullet {
        width: auto;
        color: $text-primary;
        &:light {
            color: $text-secondary;
        }
    }
    """

    symbol = reactive("\u25cf")
    """The symbol for the bullet."""

    @classmethod
    def from_symbol(cls, symbol: str):
        bullet = cls()
        bullet.symbol = symbol
        return bullet

    def get_selection(self, _selection) -> tuple[str, str] | None:
        return self.selection_text(self.symbol, _selection)

    @staticmethod
    def selection_text(symbol, selection):
        return str(symbol), " "

    def render(self) -> Content:
        return Content(self.symbol)


class MarkdownListItem(MarkdownBlock):
    """A list item Markdown block."""

    DEFAULT_CSS = """
    MarkdownListItem {
        layout: horizontal;
        margin-right: 1;
        height: auto;
    }

    MarkdownListItem > Vertical {
        width: 1fr;
        height: auto;
    }
    """

    def __init__(
        self, markdown: Markdown, token: Token, bullet: str, *,
        source_block: MarkdownSourceBlock | None = None,
    ) -> None:
        self.bullet = bullet
        super().__init__(markdown, token, source_block=source_block)

    @classmethod
    def document_node(
        cls, block, *, constructor=__init__, compose=MarkdownBlock.compose
    ):
        cls._require_native_document(constructor=constructor)
        cls._require_document_methods({"compose": compose})
        return block.node(children=[child.prepare() for child in block._blocks])


class MarkdownOrderedListItem(MarkdownListItem):
    pass


class MarkdownUnorderedListItem(MarkdownListItem):
    pass


class MarkdownFence(MarkdownBlock):
    """A fence Markdown block."""

    DEFAULT_CSS = """
    MarkdownFence {
        padding: 0;
        margin: 1 0;
        overflow: scroll hidden;
        scrollbar-size-horizontal: 0;
        scrollbar-size-vertical: 0;
        width: 1fr;
        height: auto;
        color: rgb(210,210,210);
        background: black 10%;
        &:light {
            background: white 30%;
        }
        & > Label {
            padding: 1 2;
        }
    }
    MarkdownFence:ansi {
        background: transparent;

        margin: 0;
        & > Label {
            padding: 1 0;
        }
        
    }
    """

    def __init__(
        self, markdown: Markdown, token: Token, code: str, *,
        source_block: MarkdownSourceBlock | None = None,
    ) -> None:
        super().__init__(markdown, token, source_block=source_block)
        self.code = code
        self.lexer = token.info
        self._highlighted_key: tuple[str, str, bool, bool] | None = None
        self._highlighted_code = Content()
        self._refresh_highlight()
        # No links required in code
        self.auto_links = False

    def notify_style_update(self) -> None:
        """Update highlight theme when App theme changes."""
        self._refresh_highlight()
        self.set_content(self._highlighted_code)
        return super().notify_style_update()

    def _refresh_highlight(self) -> None:
        key = (
            self.code,
            self.lexer,
            self.app.native_ansi_color,
            self.app.current_theme.dark,
        )
        highlighter = self.highlight
        native = (
            isinstance(highlighter, MethodType)
            and highlighter.__func__ is MarkdownFence.highlight.__func__
        )
        if native and self._highlighted_key == key:
            return
        source = self._source_block
        prepared = (
            source.highlight(key[2], key[3]) if source is not None else
            self._markdown._get_prepared_fence(*key) if native else None
        )
        self._highlighted_code = (
            prepared
            if prepared is not None
            else self.highlight(self.code, self.lexer, ansi=key[2], dark=key[3])
        )
        self._highlighted_key = key

    @property
    def allow_horizontal_scroll(self) -> bool:
        return True

    @classmethod
    def highlight(
        cls, code: str, language: str, ansi: bool = False, dark: bool = False
    ) -> Content:
        if ansi:
            if dark:
                from textual.highlight import ANSIDarkHighlightTheme as HighlightTheme
            else:
                from textual.highlight import ANSILightHighlightTheme as HighlightTheme

        else:
            from textual.highlight import HighlightTheme

        return highlight(code, language=language or None, theme=HighlightTheme)

    def _copy_context(self, block: MarkdownBlock) -> None:
        if isinstance(block, MarkdownFence):
            self.code = block.code
            self.lexer = block.lexer
            self._highlighted_code = block._highlighted_code
            self._highlighted_key = block._highlighted_key
        super()._copy_context(block)

    async def _update_from_block(self, block: MarkdownBlock):
        if isinstance(block, MarkdownFence):
            self._copy_context(block)
            self.set_content(block._highlighted_code)
        else:
            await super()._update_from_block(block)

    def set_content(self, content: Content) -> None:
        self._content = content
        with suppress(NoMatches):
            label = self.query_one("#code-content", Label)
            if label.content is not content:
                layout = not (
                    isinstance(label.content, Content)
                    and label.content.plain == content.plain
                )
                label.update(content, layout=layout)

    def compose(self) -> ComposeResult:
        yield self.code_label(self._highlighted_code, Label)

    @staticmethod
    def code_label(content, create):
        return create(content, id="code-content", expand=True)

    @classmethod
    def document_node(
        cls, block, *, _compose=compose, constructor=__init__, content=set_content
    ):
        cls._require_native_document(constructor=constructor, set_content=content)
        cls._require_document_methods({"compose": _compose})
        return cls.native_document_node(block)

    @classmethod
    def native_document_node(cls, block):
        return block.fence_node()

    @classmethod
    def document_declarations(cls):
        return (cls, Label)


NUMERALS = " ⅠⅡⅢⅣⅤⅥ"


class Markdown(Widget):
    DEFAULT_CSS = """
    Markdown {
        height: auto;
        padding: 0 2 0 2;
        layout: vertical;
        color: $foreground;
        overflow-y: hidden;

        &:ansi {
            MarkdownBlock > .code_inline {
                background: ansi_default !important;
            }
        }
        
        MarkdownBlock {
            &:dark > .code_inline {
                background: $warning 10%;
                color: $text-warning 95%;
            }
            &:light > .code_inline {
                background: $error 5%;
                color: $text-error 95%;
            }           
            & > .em {
                text-style: italic;
            }
            & > .strong {
                text-style: bold;
            }
            & > .s {
                text-style: strike;
            }
        }
    }
    """

    BULLETS = ["• ", "▪ ", "‣ ", "⭑ ", "◦ "]
    """Unicode bullets used for unordered lists."""

    BLOCKS: dict[str, type[MarkdownBlock]] = {
        "h1": MarkdownH1,
        "h2": MarkdownH2,
        "h3": MarkdownH3,
        "h4": MarkdownH4,
        "h5": MarkdownH5,
        "h6": MarkdownH6,
        "hr": MarkdownHorizontalRule,
        "paragraph_open": MarkdownParagraph,
        "blockquote_open": MarkdownBlockQuote,
        "bullet_list_open": MarkdownBulletList,
        "ordered_list_open": MarkdownOrderedList,
        "list_item_ordered_open": MarkdownOrderedListItem,
        "list_item_unordered_open": MarkdownUnorderedListItem,
        "table_open": MarkdownTable,
        "tbody_open": MarkdownTBody,
        "thead_open": MarkdownTHead,
        "tr_open": MarkdownTR,
        "th_open": MarkdownTH,
        "td_open": MarkdownTD,
        "fence": MarkdownFence,
        "code_block": MarkdownFence,
    }
    """Mapping of block names on to a widget class."""

    def __init__(
        self,
        markdown: str | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        parser_factory: Callable[[], MarkdownIt] | None = None,
        open_links: bool = True,
    ):
        """A Markdown widget.

        Args:
            markdown: String containing Markdown or None to leave blank for now.
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes of the widget.
            parser_factory: A factory function to return a configured MarkdownIt instance. If `None`, a "gfm-like" parser is used.
            open_links: Open links automatically. If you set this to `False`, you can handle the [`LinkClicked`][textual.widgets.markdown.Markdown.LinkClicked] events.
        """
        super().__init__(name=name, id=id, classes=classes)
        self._initial_markdown: str | None = markdown
        self._markdown = ""
        self._parser_factory = parser_factory
        self._table_of_contents: TableOfContentsType | None = None
        self._open_links = open_links
        self._last_parsed_line = 0
        self._theme = ""
        self._scene_document: MarkdownDocument | None = None

    @property
    def table_of_contents(self) -> TableOfContentsType:
        """The document's table of contents."""
        if self._table_of_contents is None:
            self._table_of_contents = list(self.heading_entries(self.children))
        return self._table_of_contents

    @staticmethod
    def heading_entries(blocks):
        """Only original top-level headings participate in native navigation."""
        for block in blocks:
            if block._is_block_type(MarkdownHeader):
                yield block.table_of_contents_entry()

    @staticmethod
    def anchor_id_for(table_of_contents, anchor: str) -> str | None:
        unique = TrackedSlugs()
        for _, title, header_id in table_of_contents:
            if unique.slug(title) == anchor:
                return header_id
        return None

    class TableOfContentsUpdated(Message):
        """The table of contents was updated."""

        def __init__(
            self, markdown: Markdown, table_of_contents: TableOfContentsType
        ) -> None:
            super().__init__()
            self.markdown: Markdown = markdown
            """The `Markdown` widget associated with the table of contents."""
            self.table_of_contents: TableOfContentsType = table_of_contents
            """Table of contents."""

        @property
        def control(self) -> Markdown:
            """The `Markdown` widget associated with the table of contents.

            This is an alias for [`TableOfContentsUpdated.markdown`][textual.widgets.Markdown.TableOfContentsSelected.markdown]
            and is used by the [`on`][textual.on] decorator.
            """
            return self.markdown

    class TableOfContentsSelected(Message):
        """An item in the TOC was selected."""

        def __init__(self, markdown: Markdown, block_id: str) -> None:
            super().__init__()
            self.markdown: Markdown = markdown
            """The `Markdown` widget where the selected item is."""
            self.block_id: str = block_id
            """ID of the block that was selected."""

        @property
        def control(self) -> Markdown:
            """The `Markdown` widget where the selected item is.

            This is an alias for [`TableOfContentsSelected.markdown`][textual.widgets.Markdown.TableOfContentsSelected.markdown]
            and is used by the [`on`][textual.on] decorator.
            """
            return self.markdown

    class LinkClicked(Message):
        """A link in the document was clicked."""

        def __init__(self, markdown: Markdown, href: str) -> None:
            super().__init__()
            self.markdown: Markdown = markdown
            """The `Markdown` widget containing the link clicked."""
            self.href: str = href
            """The original encoded URI; its consumer owns component decoding."""

        @property
        def control(self) -> Markdown:
            """The `Markdown` widget containing the link clicked.

            This is an alias for [`LinkClicked.markdown`][textual.widgets.Markdown.LinkClicked.markdown]
            and is used by the [`on`][textual.on] decorator.
            """
            return self.markdown

    @property
    def source(self) -> str:
        """The markdown source."""
        return self._markdown or ""

    def get_block_class(self, block_name: str) -> type[MarkdownBlock]:
        """Get the block widget class.

        Args:
            block_name: Name of the block.

        Returns:
            A MarkdownBlock class
        """
        return self.BLOCKS[block_name]

    async def _on_mount(self, _: Mount) -> None:
        initial_markdown = self._initial_markdown
        self._initial_markdown = None
        await self._initialize_document(initial_markdown)

    def _initialize_document(self, markdown: str | None) -> AwaitComplete:
        """Acquire initial publication and its complete document / TOC receipt.

        Ordinary Markdown mount awaits this receipt. A subclass whose body
        owner supplies preparation readiness and cancellation may observe the
        same receipt with ``call_later`` instead, after mount preprocessing.
        Acquisition is synchronous so that owner marks publication pending
        before its parent can observe mount completion. ``call_next`` still
        runs inside Mount dispatch and does not change that completion boundary.
        """
        publication = self.update(markdown or "")
        if markdown is not None:
            return publication

        async def complete_empty_document() -> None:
            await publication
            self.post_message(
                Markdown.TableOfContentsUpdated(
                    self, self._table_of_contents
                ).set_sender(self)
            )

        return AwaitComplete(complete_empty_document())

    @classmethod
    def get_stream(cls, markdown: Markdown) -> MarkdownStream:
        """Get a [MarkdownStream][textual.widgets.markdown.MarkdownStream] instance to stream Markdown in the background.

        If you append to the Markdown document many times a second, it is possible the widget won't
        be able to update as fast as you write (occurs around 20 appends per second). It will still
        work, but the user will have to wait for the UI to catch up after the document has be retrieved.

        Using a [MarkdownStream][textual.widgets.markdown.MarkdownStream] will combine several updates in to one
        as necessary to keep up with the incoming data.

        example:
        ```python
        # self.get_chunk is a hypothetical method that retrieves a
        # markdown fragment from the network
        @work
        async def stream_markdown(self) -> None:
            markdown_widget = self.query_one(Markdown)
            container = self.query_one(VerticalScroll)
            container.anchor()

            stream = Markdown.get_stream(markdown_widget)
            try:
                while (chunk:= await self.get_chunk()) is not None:
                    await stream.write(chunk)
            finally:
                await stream.stop()
        ```


        Args:
            markdown: A [Markdown][textual.widgets.Markdown] widget instance.

        Returns:
            The Markdown stream object.
        """
        updater = MarkdownStream(markdown)
        updater.start()
        return updater

    def on_markdown_link_clicked(self, event: LinkClicked) -> None:
        if self._open_links:
            self.app.open_url(event.href)

    @staticmethod
    def sanitize_location(
        location: str | PurePath | MarkdownLocation,
    ) -> MarkdownLocation:
        """Given a location, break out the path and any anchor.

        Args:
            location: The location to sanitize.

        Returns:
            The decoded filesystem path and separate anchor as one owned
            navigation resource. Path values are literal filesystem spellings.
        """
        if isinstance(location, MarkdownLocation):
            return location
        if isinstance(location, PurePath):
            return MarkdownLocation(Path(location))
        path, _, anchor = location.partition("#")
        return MarkdownLocation(Path(unquote(path)), unquote(anchor))

    def goto_anchor(self, anchor: str) -> bool:
        """Try and find the given anchor in the current document.

        Args:
            anchor: The anchor to try and find.

        Note:
            The anchor is found by looking at all of the headings in the
            document and finding the first one whose slug matches the
            anchor.

            Note that the slugging method used is similar to that found on
            GitHub.

        Returns:
            True when the anchor was found in the current document, False otherwise.
        """
        if not self._table_of_contents or not isinstance(self.parent, Widget):
            return False
        header_id = self.anchor_id_for(self._table_of_contents, anchor)
        if header_id is not None:
            self.query_one(f"#{header_id}").scroll_visible(top=True)
            return True
        return False

    async def load(self, path: Path | MarkdownLocation) -> None:
        """Load a new Markdown document.

        Args:
            path: Path to the document.

        Raises:
            OSError: If there was some form of error loading the document.

        Note:
            The exceptions that can be raised by this method are all of
            those that can be raised by calling [`Path.read_text`][pathlib.Path.read_text].
        """
        await self.sanitize_location(path).load(self)

    def _get_token_content(self, token: Token, *, block: MarkdownBlock) -> Content:
        """Supply inline content for every block, including headings and tables.

        Prepared documents may return their acquired content here; ordinary
        documents use the same native conversion without a separate parser.
        """
        return block._token_to_content(token)

    def acquire_document_content(self):
        """Acquire a data-only prepared inline supplier, not a live widget hook."""
        if type(self)._get_token_content is not Markdown._get_token_content:
            raise TypeError(
                f"{type(self).__name__} must supply acquire_document_content"
            )
        return None

    def acquire_document_fences(self):
        """Acquire a data-only prepared fence supplier, or native highlighting."""
        return None

    def acquire_document_unhandled(self):
        """Data-only source extension for a custom parsed token grammar."""
        if type(self).unhandled_token is not Markdown.unhandled_token:
            raise TypeError(
                f"{type(self).__name__} must supply acquire_document_unhandled"
            )
        return None

    def acquire_document_blocks(self):
        """The original declaration catalog; dynamic factories supply their snapshot."""
        if type(self).get_block_class is not Markdown.get_block_class:
            raise TypeError(
                f"{type(self).__name__} must supply acquire_document_blocks"
            )
        return self.BLOCKS.copy()

    def get_document_process_layout(self):
        """Data-only layout processing; custom scene hooks must supply it."""
        if type(self).process_layout is not Widget.process_layout:
            raise TypeError(
                f"{type(self).__name__} must supply get_document_process_layout"
            )
        return None

    def get_document_ancestor_pseudo_classes(self) -> frozenset[str] | None:
        """Declare non-CSS ancestor observations used by detached source hooks.

        None retains the full observation for arbitrary factories, converters
        and layout hooks. An explicit set adds those observations to the actual
        prepared stylesheet's dependencies; an empty set declares CSS-only
        ancestor input. This includes required predicate side effects, not just
        returned booleans. The root's native source observation remains full.
        """
        return None

    @classmethod
    def document_root(
        cls,
        document,
        children,
        *,
        render=Widget.render,
        width=Widget.get_content_width,
        height=Widget.get_content_height,
        pre_layout=Widget.pre_layout,
        empty=Widget.is_empty,
        pseudo_classes=Widget.get_pseudo_classes,
    ):
        """Native immutable root; custom scene semantics supply this producer."""
        cls._require_document_methods(
            {
                "render": render,
                "get_content_width": width,
                "get_content_height": height,
                "pre_layout": pre_layout,
                "is_empty": empty,
                "get_pseudo_classes": pseudo_classes,
            }
        )
        return cls.native_document_root(document, children)

    @classmethod
    def native_document_root(cls, document, children):
        """Shared intrinsic block layout, independent of scene BodyMeasurement."""
        return document.root_node(children)

    def acquire_document(self, source: str, tokens: Sequence[Token]):
        """Freeze source, declarations and effective presentation for workers.

        Tokens belong to the actual parser/link resolver. This method never
        reparses the source or reads a current file to replace their wording.
        The result prepares paint/extents without mounting any descendants.
        """
        from textual.document._markdown import MarkdownDocument

        return MarkdownDocument.acquire(self, source, tokens)

    def action_link(self, href: str) -> None:
        """Dispatch a link from mounted blocks or original detached placements."""
        self.post_message(Markdown.LinkClicked(self, href))

    def unhandled_token(self, token: Token) -> MarkdownBlock | None:
        """Process an unhandled token.

        Args:
            token: The MarkdownIt token to handle.

        Returns:
            Either a widget to be added to the output, or `None`.
        """
        return None

    @staticmethod
    def _build_blocks(tokens: Iterable[Token], create, unhandled, bullets):
        """The one native token grammar for scene and detached resources.

        Factory and unknown-token behavior are acquired by their actual owner.
        None marks token progress; scene construction retains cooperative turns.
        """
        stack: list[MarkdownBlock] = []
        stack_append = stack.append

        for token in tokens:
            emitted = None
            token_type = token.type
            if token_type == "heading_open":
                stack_append(create(token.tag, token))
            elif token_type == "hr":
                emitted = create("hr", token)
            elif token_type == "paragraph_open":
                stack_append(create("paragraph_open", token))
            elif token_type == "blockquote_open":
                stack_append(create("blockquote_open", token))
            elif token_type == "bullet_list_open":
                stack_append(create("bullet_list_open", token))
            elif token_type == "ordered_list_open":
                stack_append(create("ordered_list_open", token))
            elif token_type == "list_item_open":
                if token.info:
                    stack_append(create("list_item_ordered_open", token, token.info))
                else:
                    item_count = sum(
                        1
                        for block in stack
                        if block._is_block_type(MarkdownUnorderedListItem)
                    )
                    stack_append(
                        create(
                            "list_item_unordered_open",
                            token,
                            bullets[item_count % len(bullets)],
                        )
                    )
            elif token_type == "table_open":
                stack_append(create("table_open", token))
            elif token_type == "tbody_open":
                stack_append(create("tbody_open", token))
            elif token_type == "thead_open":
                stack_append(create("thead_open", token))
            elif token_type == "tr_open":
                stack_append(create("tr_open", token))
            elif token_type == "th_open":
                stack_append(create("th_open", token))
            elif token_type == "td_open":
                stack_append(create("td_open", token))
            elif token_type.endswith("_close"):
                block = stack.pop()
                if token.type == "heading_close":
                    block.id = block.heading_id()
                if stack:
                    stack[-1]._blocks.append(block)
                else:
                    emitted = block
            elif token_type == "inline":
                stack[-1].build_from_token(token)
            elif token_type in ("fence", "code_block"):
                fence = create(token_type, token, token.content.rstrip())
                assert fence._is_block_type(MarkdownFence)
                if stack:
                    stack[-1]._blocks.append(fence)
                else:
                    emitted = fence
            else:
                external = unhandled(token)
                if external is not None:
                    if stack:
                        stack[-1]._blocks.append(external)
                    else:
                        emitted = external
            yield emitted

    async def _parse_markdown(
        self, tokens: Iterable[Token]
    ) -> AsyncIterator[MarkdownBlock]:
        def create(name, token, *args):
            return self.get_block_class(name)(self, token, *args)

        steps = iter(
            self._build_blocks(tokens, create, self.unhandled_token, self.BULLETS)
        )
        while True:
            await asyncio.sleep(0)
            try:
                block = next(steps)
            except StopIteration:
                break
            if block is not None:
                yield block

    async def _parse_tokens(
        self, parser: MarkdownIt, markdown: str, *, use_thread: bool
    ) -> list[Token] | None:
        """Parse before constructing widgets; None discards a superseded request."""
        if use_thread:
            return await asyncio.get_running_loop().run_in_executor(
                None, parser.parse, markdown
            )
        return parser.parse(markdown)

    def _get_prepared_fence(
        self, code: str, language: str, ansi: bool, dark: bool
    ) -> Content | None:
        """Optional data-only highlighting prepared by the document parser."""
        return None

    async def _replace_blocks(self, blocks: AsyncIterator[MarkdownBlock]) -> None:
        """Commit original completed roots through the one native mount owner."""
        previous = self.query("MarkdownBlock")
        removed = False
        async for block in blocks:
            if removed:
                await self.mount(block)
            else:
                async with self.batch():
                    await previous.remove()
                    await self.mount(block)
                removed = True
        if not removed:
            await previous.remove()

    def _complete_update(self, tokens: Sequence[Token]) -> None:
        # append() replaces the final root, not merely the final physical line.
        self._table_of_contents = None
        self._last_parsed_line = next(
            (
                token.map[0]
                for token in reversed(tokens)
                if token.map is not None and token.level == 0
            ),
            0,
        )
        self.post_message(
            Markdown.TableOfContentsUpdated(self, self.table_of_contents).set_sender(self)
        )

    def materialize_document(self, paint: DocumentPaint) -> AwaitComplete:
        """Rebuild interaction controls from the actual acquired grammar roots.

        Paint is the original completed grammar cohort, not a request to parse
        equal source again. Its members and resolved suppliers bind directly
        to the real controls; current scene CSS still owns their placement.
        Ordinary update/append retain their parser, extension and streaming
        contracts and invalidate this binding when they accept a new source.
        """
        document = paint.document
        if document.declaration is not type(self):
            raise TypeError("Acquired Markdown belongs to a different scene declaration")
        if any(not document.same_source(root.document) for root in paint.roots):
            raise ValueError("Acquired roots belong to a different Markdown source")
        previous = self._scene_document
        self._scene_document = document
        if not self.is_current_document(document):
            self._scene_document = previous
            raise ValueError("Acquired Markdown is no longer the owner's current source")
        self._theme = self.app.theme
        self._markdown = document.source
        self._table_of_contents = None

        async def blocks():
            for source in paint.roots:
                block = await source.declaration.from_source(self, source)
                if not self.is_current_document(document):
                    return
                yield block

        async def materialize():
            async with self.lock:
                if not self.is_current_document(document):
                    return
                await self._replace_blocks(blocks())
                if not self.is_current_document(document):
                    return
                self._complete_update(document.tokens)

        return AwaitComplete(materialize())

    def is_current_document(self, document: MarkdownDocument) -> bool:
        """Admit source lineage through the Markdown owner's current resource.

        Native update/append revoke scene custody independently of a subclass
        source publication. Both facts must agree; a current acquired document
        cannot re-admit controls consumed by an older native source request.
        """
        scene = self._scene_document
        current = self.get_current_document()
        return (
            scene is not None and scene.same_source(document)
            and current is not None
            and (current is scene or current.same_source(document))
        )

    def get_current_document(self) -> MarkdownDocument | None:
        """The current source resource, independent of style/width inputs.

        Acquired-source subclasses supply their original current document here
        without duplicating native scene-admission or update/append decisions.
        """
        return self._scene_document

    def update(self, markdown: str) -> AwaitComplete:
        """Update the document with new Markdown.

        Args:
            markdown: A string containing Markdown.

        Returns:
            An optionally awaitable object. Await this to ensure that all children have been mounted.
        """
        self._theme = self.app.theme
        parser = (
            MarkdownIt("gfm-like")
            if self._parser_factory is None
            else self._parser_factory()
        )

        self._markdown = markdown
        self._scene_document = None
        self._table_of_contents = None

        async def await_update() -> None:
            """Construct and complete each original root before starting the next."""

            # Lock so that you can't update with more than one document simultaneously
            async with self.lock:
                tokens = await self._parse_tokens(parser, markdown, use_thread=True)
                if tokens is None:
                    return

                await self._replace_blocks(self._parse_markdown(tokens))

            self._complete_update(tokens)

        return AwaitComplete(await_update())

    def append(self, markdown: str) -> AwaitComplete:
        """Append to markdown.

        Args:
            markdown: A fragment of markdown to be appended.

        Returns:
            An optionally awaitable object. Await this to ensure that the markdown has been append by the next line.
        """
        parser = (
            MarkdownIt("gfm-like")
            if self._parser_factory is None
            else self._parser_factory()
        )

        self._markdown = self.source + markdown
        self._scene_document = None
        updated_source = "".join(
            self._markdown.splitlines(keepends=True)[self._last_parsed_line :]
        )

        async def await_append() -> None:
            """Append new markdown widgets."""
            async with self.lock:
                tokens = await self._parse_tokens(
                    parser, updated_source, use_thread=False
                )
                if tokens is None:
                    return
                existing_blocks = [
                    child for child in self.children if isinstance(child, MarkdownBlock)
                ]
                start_line = self._last_parsed_line
                for token in reversed(tokens):
                    if token.map is not None and token.level == 0:
                        self._last_parsed_line += token.map[0]
                        break

                new_blocks = [block async for block in self._parse_markdown(tokens)]
                any_headers = any(
                    isinstance(block, MarkdownHeader) for block in new_blocks
                )
                for block in new_blocks:
                    start, end = block.source_range
                    block.source_range = (
                        start + start_line,
                        end + start_line,
                    )

                async with self.batch():
                    if existing_blocks and new_blocks:
                        last_block = existing_blocks[-1]
                        last_block.source_range = new_blocks[0].source_range
                        try:
                            await last_block._update_from_block(new_blocks[0])
                        except IndexError:
                            pass
                        else:
                            new_blocks = new_blocks[1:]

                    for block in new_blocks:
                        await self.mount(block)

                if any_headers:
                    self._table_of_contents = None
                    self.post_message(
                        Markdown.TableOfContentsUpdated(
                            self, self.table_of_contents
                        ).set_sender(self)
                    )

        return AwaitComplete(await_append())


class MarkdownTableOfContents(Widget, can_focus_children=True):
    """Displays a table of contents for a markdown document."""

    DEFAULT_CSS = """
    MarkdownTableOfContents {
        width: auto;
        height: 1fr;
        background: $panel;
        &:focus-within {
            background-tint: $foreground 5%;
        }
    }
    MarkdownTableOfContents > Tree {
        padding: 1;
        width: auto;
        height: 1fr;
        background: $panel;
    }
    """

    table_of_contents = reactive[Optional[TableOfContentsType]](None, init=False)
    """Underlying data to populate the table of contents widget."""

    def __init__(
        self,
        markdown: Markdown,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        """Initialize a table of contents.

        Args:
            markdown: The Markdown document associated with this table of contents.
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes for the widget.
            disabled: Whether the widget is disabled or not.
        """
        self.markdown: Markdown = markdown
        """The Markdown document associated with this table of contents."""
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)

    def compose(self) -> ComposeResult:
        tree: Tree = Tree("TOC")
        tree.show_root = False
        tree.show_guides = True
        tree.guide_depth = 4
        tree.auto_expand = False
        yield tree

    def watch_table_of_contents(self, table_of_contents: TableOfContentsType) -> None:
        """Triggered when the table of contents changes."""
        self.rebuild_table_of_contents(table_of_contents)

    def rebuild_table_of_contents(self, table_of_contents: TableOfContentsType) -> None:
        """Rebuilds the tree representation of the table of contents data.

        Args:
            table_of_contents: Table of contents.
        """
        tree = self.query_one(Tree)
        tree.clear()
        root = tree.root
        for level, name, block_id in table_of_contents:
            node = root
            for _ in range(level - 1):
                if node._children:
                    node = node._children[-1]
                    node.expand()
                    node.allow_expand = True
                else:
                    node = node.add(NUMERALS[level], expand=True)
            node_label = Text.assemble((f"{NUMERALS[level]} ", "dim"), name)
            node.add_leaf(node_label, {"block_id": block_id})

    async def _on_tree_node_selected(self, message: Tree.NodeSelected) -> None:
        node_data = message.node.data
        if node_data is not None:
            await self._post_message(
                Markdown.TableOfContentsSelected(self.markdown, node_data["block_id"])
            )
        message.stop()


class MarkdownViewer(VerticalScroll, can_focus=False, can_focus_children=True):
    """A Markdown viewer widget."""

    SCOPED_CSS = False

    DEFAULT_CSS = """
    MarkdownViewer {
        height: 1fr;
        scrollbar-gutter: stable;
        background: $surface;
        & > MarkdownTableOfContents {
            display: none;
            dock:left;
        }
    }

    MarkdownViewer.-show-table-of-contents > MarkdownTableOfContents {
        display: block;
    }
    """

    show_table_of_contents = reactive(True)
    """Show the table of contents?"""
    top_block = reactive("")

    navigator: var[Navigator] = var(Navigator)

    class NavigatorUpdated(Message):
        """Navigator has been changed (clicked link etc)."""

    def __init__(
        self,
        markdown: str | None = None,
        *,
        show_table_of_contents: bool = True,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        parser_factory: Callable[[], MarkdownIt] | None = None,
        open_links: bool = True,
    ):
        """Create a Markdown Viewer object.

        Args:
            markdown: String containing Markdown, or None to leave blank.
            show_table_of_contents: Show a table of contents in a sidebar.
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes of the widget.
            parser_factory: A factory function to return a configured MarkdownIt instance. If `None`, a "gfm-like" parser is used.
            open_links: Open links automatically. If you set this to `False`, you can handle the [`LinkClicked`][textual.widgets.markdown.Markdown.LinkClicked] events.
        """
        super().__init__(name=name, id=id, classes=classes)
        self.show_table_of_contents = show_table_of_contents
        self._markdown = markdown
        self._parser_factory = parser_factory
        self._open_links = open_links

    @property
    def document(self) -> Markdown:
        """The [`Markdown`][textual.widgets.Markdown] document widget."""
        return self.query_one(Markdown)

    @property
    def table_of_contents(self) -> MarkdownTableOfContents:
        """The [table of contents][textual.widgets.markdown.MarkdownTableOfContents] widget."""
        return self.query_one(MarkdownTableOfContents)

    async def _on_mount(self, _: Mount) -> None:
        await self.document.update(self._markdown or "")

    async def go(self, location: str | PurePath) -> None:
        """Navigate to a new document path."""
        target = self.document.sanitize_location(location)
        if target.path == Path(".") and target.anchor:
            # We've been asked to go to an anchor but with no file specified.
            self.document.goto_anchor(target.anchor)
        else:
            # We've been asked to go to a file, optionally with an anchor.
            await self.document.load(self.navigator.go(target))
            self.post_message(self.NavigatorUpdated())

    async def back(self) -> None:
        """Go back one level in the history."""
        if self.navigator.back():
            await self.document.load(self.navigator.location)
            self.post_message(self.NavigatorUpdated())

    async def forward(self) -> None:
        """Go forward one level in the history."""
        if self.navigator.forward():
            await self.document.load(self.navigator.location)
            self.post_message(self.NavigatorUpdated())

    async def _on_markdown_link_clicked(self, message: Markdown.LinkClicked) -> None:
        message.stop()
        await self.go(message.href)

    def watch_show_table_of_contents(self, show_table_of_contents: bool) -> None:
        self.set_class(show_table_of_contents, "-show-table-of-contents")

    def compose(self) -> ComposeResult:
        markdown = Markdown(
            parser_factory=self._parser_factory, open_links=self._open_links
        )
        markdown.can_focus = True
        yield markdown
        yield MarkdownTableOfContents(markdown)

    def _on_markdown_table_of_contents_updated(
        self, message: Markdown.TableOfContentsUpdated
    ) -> None:
        self.query_one(MarkdownTableOfContents).table_of_contents = (
            message.table_of_contents
        )
        message.stop()

    def _on_markdown_table_of_contents_selected(
        self, message: Markdown.TableOfContentsSelected
    ) -> None:
        block_selector = f"#{message.block_id}"
        block = self.query_one(block_selector, MarkdownBlock)
        self.scroll_to_widget(block, top=True)
        message.stop()
