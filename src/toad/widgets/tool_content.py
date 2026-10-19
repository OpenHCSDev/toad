"""The shared line-block view for live tool details and permission previews."""
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.geometry import Size
from textual._paint_state import PaintState
from textual.strip import Strip
from textual.widget import Widget
from textual.worker import Worker
from toad.block_content import BlockContent
from toad.markdown_links import LinkContext, ReferenceRendering
from toad.line_blocks import LineBlock
from toad.widgets.linked_rows import HorizontalRows, selection_painted
from toad.widgets.transcript_lines import (
    BlockLines, LinePreparation, Lines, PlainLines, TranscriptLinesRenderTask, link_place,
)


class ToolContent(ReferenceRendering, HorizontalRows, BlockContent, Widget):
    """One live details widget painting the parts' canonical line blocks."""

    DEFAULT_CSS = "ToolContent { height: auto; overflow-x: auto; overflow-y: hidden; }"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.blocks: tuple[LineBlock, ...] = ()
        self._styled: BlockLines | None = None
        self._plain: PlainLines | None = None
        self._width = 0
        self._link_place = link_place()
        self._render_worker: Worker[None] | None = None

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self.invalidate_lines)
        self._request_render()

    def invalidate_lines(self, change=None) -> None:
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
        if styled is not None:
            self._styled = styled.rewrap(width)
            return self._styled
        return self._plain_lines(width)

    def _plain_lines(self, width: int) -> PlainLines:
        if self._plain is None or self._plain.width != width:
            self._plain = PlainLines(width, self.app.colours.line_renderer, self.blocks)
        return self._plain

    @property
    def line_sets(self) -> tuple[Lines, ...]:
        return (self._lines(self._width),) if self._width else ()

    def _request_render(self) -> None:
        if self._width and self.is_attached:
            self._render_worker = self.run_worker(
                self._render, group="tool-details", exclusive=True
            )

    async def _render(self) -> None:
        blocks, theme = self.blocks, self.app.colours.line_theme
        preparation = LinePreparation(blocks, theme)
        context = await LinkContext.acquire(self)
        source = await self.app.render_processes.submit(
            TranscriptLinesRenderTask(preparation, context)
        )
        if not context.current_for(self):
            self.call_later(self._request_render)
            return
        if self.is_attached and (blocks, theme) == (self.blocks, self.app.colours.line_theme):
            previous_height = self._lines(self._width).height
            previous_width = self._lines(self._width).content_width
            self._styled = lines = source.wrap(self._width, self.app.colours.line_renderer)
            self.refresh(layout=(previous_height, previous_width) != (lines.height, lines.content_width))

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        if width != self._width:
            self._width = width
            self._plain = None
            if self._styled is None:
                self.call_later(self._request_render)
        return self._lines(width).height

    def render_line(self, y: int, paint: PaintState) -> Strip:
        width = self._width
        strips = self._lines(width).strips_at(self._link_place) if width else ()
        if y >= len(strips):
            return self.blank_row(width, paint)
        return selection_painted(self, self.on_background(strips[y], paint, y), y)

    def get_clipboard_text(self) -> str:
        return "\n".join(block.selection_text for block in self.blocks)
