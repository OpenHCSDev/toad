"""A live block's drawn rows: worker-styled lines are their only height."""

from __future__ import annotations

import asyncio
from abc import abstractmethod

from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual._paint_state import PaintState
from textual.geometry import Size
from textual.strip import Strip
from textual.worker import Worker

from toad.line_blocks import LineBlock
from toad.markdown_links import LinkContext
from toad.widgets.linked_rows import LinkedRows
from toad.widgets.transcript_lines import (
    BlockLines, LinePreparation, Lines, PreparedLines, TranscriptLinesRenderTask, link_place,
)


class StyledRows(LinkedRows):
    """Rows the render worker styled from `styled_blocks()`, wrapped locally to the width.

    Styled lines are the block's only height, as they are a transcript fragment's. The worker's
    styled source is independent of width; every reader wraps it at the width it is asked about
    (layout) or the widget's own content width (paint), so layout and paint never disagree when
    Textual reuses a cached measurement. Before its first render a block draws no rows;
    afterwards it keeps its last styled source until the next render replaces it, so a restyle
    (theme, link context) recolours without moving a row, and new content changes the height
    once, when its rows arrive.
    """

    RESTYLE_INTERVAL = 0.25
    _prepared: LinePreparation | None = None
    _styled: BlockLines | None = None
    _render_worker: Worker[None] | None = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._link_place = link_place()

    @abstractmethod
    def styled_blocks(self) -> tuple[LineBlock, ...]:
        """The semantic rows the next render styles."""

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self.invalidate_lines)

    def invalidate_lines(self, change=None) -> None:
        """Restyle for a new theme or link context; the drawn rows stand until then."""
        self._request_render()

    def restyle(self) -> None:
        """The blocks changed; their rows arrive with the next render."""
        self._request_render()

    def _lines(self, width: int) -> Lines:
        """The styled rows at this width: the styled source wrapped locally."""
        prepared = self._prepared
        if prepared is None or not width:
            return PreparedLines(width, ())
        styled = self._styled
        self._styled = styled = (prepared.wrap(width, self.app.colours.line_renderer)
                                 if styled is None else styled.rewrap(width))
        return styled

    @property
    def line_sets(self) -> tuple[Lines, ...]:
        width = self.content_size.width
        return (self._lines(width),) if width else ()

    def _request_render(self) -> None:
        if self.is_attached and (self._render_worker is None or self._render_worker.is_finished):
            # A widget worker: unmount cancels it and a failure is an app error.
            self._render_worker = self.run_worker(self._render_latest(), group="styled-rows")

    async def _render_latest(self) -> None:
        """Style the current blocks; while they keep changing, again at a bounded rate."""
        renderer = self.app.render_processes
        while self.is_attached:
            blocks, theme = self.styled_blocks(), self.app.colours.line_theme
            context = await LinkContext.acquire(self)
            prepared = await renderer.submit(TranscriptLinesRenderTask(LinePreparation(blocks, theme), context))
            if not self.is_attached:
                return
            if not context.current_for(self) or theme is not self.app.colours.line_theme:
                continue
            width = self.content_size.width
            before = self._lines(width)
            self._prepared, self._styled = prepared, None
            after = self._lines(width)
            self.refresh(layout=(before.height, before.content_width) != (after.height, after.content_width))
            if blocks == self.styled_blocks():
                return
            await asyncio.sleep(self.RESTYLE_INTERVAL)

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        # The styled rows at this width; the container's height is never read.
        if self._prepared is None:
            self.call_later(self._request_render)
        return self._lines(width).height

    def painted_row(self, strip: Strip, y: int) -> Strip:
        return strip

    def render_line(self, y: int, paint: PaintState) -> Strip:
        width = self.content_size.width
        strips = self._lines(width).strips_at(self._link_place) if width else ()
        if y >= len(strips):
            return self.blank_row(width, paint)
        # Prepared rows span exactly this width (Lines.strips_at).
        return self.painted_row(self.on_background(strips[y], paint, y), y)
