"""Live and committed bodies retain worker-styled source and wrap it locally.

Source appends coalesce while styling; resizing never requests source styling.
"""

from __future__ import annotations

import asyncio
from bisect import bisect_right

from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.geometry import Size
from textual.selection import Selection
from textual._paint_state import PaintState
from textual.strip import Strip
from textual.widget import Widget
from textual.worker import Worker

from toad.block_content import BlockContent
from toad.markdown_links import LinkContext, ReferenceRendering
from toad.line_blocks import Body, MarkdownBody, LineBlock, LineRole, TextRole
from toad.widgets.linked_rows import LinkedRows
from toad.widgets.transcript_lines import (
    BlockLines, JoinedLines, Lines, LinePreparation, PreparedLines, TranscriptLinesRenderTask, link_place,
)


class LineMarkdown(ReferenceRendering, LinkedRows, BlockContent, Widget):
    """Draw the declared body; selection copies the original source text."""

    DEFAULT_CSS = "LineMarkdown { height: auto; }"
    RESTYLE_INTERVAL = 0.25

    def __init__(self, text: str = "", *, role: type[LineRole] = TextRole,
                 bar: type[LineRole] | None = None, body: type[Body] = MarkdownBody,
                 id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.text = text
        self.role, self.bar, self.body_type = role, bar, body
        self._styled: BlockLines | None = None
        self._plain: Lines | None = None
        self._width = 0
        self._link_place = link_place()
        self._render_worker: Worker[None] | None = None

    def line_blocks(self, text: str, *, complete: bool = True) -> tuple[LineBlock, ...]:
        """Semantic rows for this text; streaming subclasses may add a final row."""
        return (self.body_type(text, role=self.role, bar=self.bar),)

    @property
    def block(self) -> LineBlock:
        return self.line_blocks(self.text)[0]

    def get_clipboard_text(self) -> str | None:
        return self.text or None

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self.invalidate_lines)

    def invalidate_lines(self, change=None) -> None:
        self._styled, self._styled_text, self._plain = None, "", None
        self._request_render()
        self.refresh(layout=True)

    def update(self, text: str) -> None:
        """Replace the text; the drawn rows follow without blocking."""
        if text != self.text:
            rows = self._row_count()
            # A completed stream may own a final semantic row (for example the
            # gap after thinking). It cannot remain inside a styled prefix once
            # more text follows it.
            if self.line_blocks(self.text, complete=True) != self.line_blocks(
                self.text, complete=False
            ):
                self._styled, self._styled_text = None, ""
            self._plain = None
            self.text = text
            self._request_render()
            self._redraw(rows)

    def _row_count(self) -> int | None:
        return self._lines(self._width).height if self._width else None

    def _redraw(self, rows: int | None) -> None:
        """Repaint; lay out again only when the height changed.

        Most streamed chunks extend the current row, and a layout request
        re-arranges the whole screen.
        """
        self.refresh(layout=rows is None or rows != self._row_count())

    def append(self, text: str) -> None:
        self.update(self.text + text)

    def _plain_rows(self, text: str, width: int, *, complete: bool = True):
        return self.app.colours.line_renderer.at_width(width).rows(
            self.line_blocks(text, complete=complete)
        )

    def _lines(self, width: int) -> Lines:
        """Styled rows for the text they cover, then plain rows for anything newer.

        While a response streams, earlier text keeps its styled rows and only
        the appended tail draws plain until the next render replaces both.
        """
        styled, covered = self._styled, self._styled_text
        if styled is not None:
            self._styled = styled = styled.rewrap(width)
        if self._plain is not None and self._plain.width == width:
            return self._plain
        tail = self.text[len(covered):] if self.text.startswith(covered) else None
        # A styled prefix is drawn only whole or ending at a paragraph
        # boundary; anything else would split the paragraph it ends in.
        if styled is not None and tail is not None and (
                not tail or tail.startswith("\n\n")):
            if not tail:
                return styled
            # The separator and new paragraphs belong only to the plain tail.
            plain = PreparedLines(width, ((),) + self._plain_rows(
                tail.lstrip("\n"), width, complete=True))
            self._plain = JoinedLines(styled, plain)
        else:
            self._plain = PreparedLines(width, self._plain_rows(self.text, width))
        return self._plain

    _styled_text = ""

    def _request_render(self) -> None:
        if self._width and self.is_attached and (self._render_worker is None or self._render_worker.is_finished):
            # A widget worker: unmount cancels it and a failure is an app error.
            self._render_worker = self.run_worker(self._render_latest(), group="restyle")

    @staticmethod
    def _complete_paragraphs(text: str) -> str:
        """The text up to its last blank line: paragraphs no later chunk extends."""
        end = text.rfind("\n\n")
        return text[:end] if end > 0 else ""

    async def _render_latest(self) -> None:
        renderer = self.app.render_processes
        seen = None
        while self.is_attached:
            text, theme = self.text, self.app.colours.line_theme
            # While text keeps arriving, style only complete paragraphs, so
            # the plain tail never splits one. Unchanged for an interval (or a
            # one-shot update), style all of it.
            target = text if seen is None or seen == text else self._complete_paragraphs(text)
            seen = text
            styled = self._styled
            if target and (target != self._styled_text or styled is None):
                complete = target == self.text
                blocks = self.line_blocks(target, complete=complete)
                context = await LinkContext.acquire(self)
                source = await renderer.submit(TranscriptLinesRenderTask(LinePreparation(blocks, theme), context))
                if not context.current_for(self):
                    continue
                if not self.is_attached:
                    return
                source_current = theme is self.app.colours.line_theme
                if source_current and self.text.startswith(target):
                    # A completed render includes final spacing; unlike a
                    # prefix render, it belongs only to that exact text.
                    if not complete or self.text == target:
                        rows = self._row_count()
                        self._styled, self._styled_text = source.wrap(self._width, self.app.colours.line_renderer), target
                        self._plain = None
                        self._redraw(rows)
            if target == self.text:
                return
            # Text is still arriving. The plain tail already shows it, so
            # restyle at a bounded rate instead of re-rendering the whole
            # message after every fragment.
            await asyncio.sleep(self.RESTYLE_INTERVAL)

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        # The text wrapped at this width; the container's height is never read.
        if width != self._width:
            self._width = width
            if self._styled is None:
                self.call_later(self._request_render)
        return self._lines(width).height

    def render_line(self, y: int, paint: PaintState) -> Strip:
        width = self._width
        strips = self._lines(width).strips_at(self._link_place) if width else ()
        if y >= len(strips):
            return self.blank_row(width, paint)
        # Prepared rows span exactly this width (Lines.strips_at).
        return self.on_background(strips[y], paint, y)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        return selection.extract(self.text), "\n"
