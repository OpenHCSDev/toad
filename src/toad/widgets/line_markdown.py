"""Markdown text drawn as prepared lines, for live and committed messages alike.

The text is a `Body` line block. Plain rows draw immediately; styled rows come
from the render worker processes and replace them when ready. Appends while a
render is in flight are coalesced: one render runs at a time and the latest
text is rendered next.
"""

from __future__ import annotations

import asyncio
from bisect import bisect_right

from textual.geometry import Size
from textual.selection import Selection
from textual.strip import Strip
from textual.widget import Widget

from toad.line_blocks import Body, LineRole, TextRole
from toad.widgets.transcript_lines import (
    LineTheme, PreparedLines, RichLineRenderer, TranscriptLinesRenderTask,
)


class LineMarkdown(Widget):
    """A leaf that draws one Markdown body; its owner holds headers and identity."""

    DEFAULT_CSS = "LineMarkdown { height: auto; }"
    RESTYLE_INTERVAL = 0.25

    def __init__(self, text: str = "", *, role: type[LineRole] = TextRole,
                 bar: type[LineRole] | None = None, markdown: bool = True,
                 id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.text = text
        self.role, self.bar, self.markdown = role, bar, markdown
        self._theme: LineTheme | None = None
        self._styled: PreparedLines | None = None
        self._plain: PreparedLines | None = None
        self._width = 0
        self._render: asyncio.Task[None] | None = None

    @property
    def block(self) -> Body:
        return Body(self.text, role=self.role, bar=self.bar, markdown=self.markdown)

    def on_mount(self) -> None:
        self.watch(self.app, "theme", self._theme_changed, init=False)

    def _theme_changed(self) -> None:
        self._theme = None
        self._styled, self._styled_text, self._plain = None, "", None
        self._request_render()
        self.refresh(layout=True)

    def on_unmount(self) -> None:
        if self._render is not None:
            self._render.cancel()

    def update(self, text: str) -> None:
        """Replace the text; the drawn rows follow without blocking."""
        if text != self.text:
            self.text = text
            self._request_render()
            self.refresh(layout=True)

    def append(self, text: str) -> None:
        self.update(self.text + text)

    def _line_theme(self) -> LineTheme:
        if self._theme is None:
            self._theme = LineTheme.from_app(self.app)
        return self._theme

    def _plain_rows(self, text: str, width: int):
        return RichLineRenderer(self._line_theme(), width, plain=True).rows((
            Body(text, role=self.role, bar=self.bar, markdown=False),))

    def _lines(self, width: int) -> PreparedLines:
        """Styled rows for the text they cover, then plain rows for anything newer.

        While a response streams, earlier text keeps its styled rows and only
        the appended tail draws plain until the next render replaces both.
        """
        styled, covered = self._styled, self._styled_text
        if styled is not None and styled.width == width and self.text.startswith(covered):
            if len(covered) == len(self.text):
                return styled
            key = (width, len(self.text), id(styled))
            if self._plain is None or self._plain_key != key:
                self._plain = PreparedLines(width, styled.rows + self._plain_rows(
                    self.text[len(covered):].lstrip("\n"), width))
                self._plain_key = key
            return self._plain
        key = (width, len(self.text), None)
        if self._plain is None or self._plain_key != key:
            self._plain = PreparedLines(width, self._plain_rows(self.text, width))
            self._plain_key = key
        return self._plain

    _styled_text = ""
    _plain_key: tuple | None = None

    def _request_render(self) -> None:
        if self._width and self.is_attached and (self._render is None or self._render.done()):
            self._render = asyncio.create_task(self._render_latest())

    async def _render_latest(self) -> None:
        renderer = self.app.render_processes
        while self.is_attached:
            text, width, theme = self.text, self._width, self._line_theme()
            try:
                lines = await renderer.submit(TranscriptLinesRenderTask((self.block,), width, theme))
            except Exception:
                return  # Plain rows stay; the next update requests again.
            if not self.is_attached:
                return
            if width == self._width and theme is self._line_theme():
                self._styled, self._styled_text = lines, text
                self.refresh(layout=True)
            if (text, width) == (self.text, self._width):
                return
            # Text is still arriving. The plain tail already shows it, so
            # restyle at a bounded rate instead of re-rendering the whole
            # message after every fragment.
            await asyncio.sleep(self.RESTYLE_INTERVAL)

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        if width != self._width:
            self._width = width
            self._request_render()
        return len(self._lines(width).rows)

    def render_line(self, y: int) -> Strip:
        width = self._width
        strips = self._lines(width).strips if width else ()
        if y >= len(strips):
            return Strip.blank(width)
        return strips[y].extend_cell_length(width).crop(0, width)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Selected text comes from the source text, not from drawn cells."""
        return selection.extract(self.text), "\n"
