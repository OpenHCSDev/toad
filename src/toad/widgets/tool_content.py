"""The shared line-block view for live tool details and permission previews."""
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.geometry import Size
from textual.strip import Strip
from textual.widget import Widget
from textual.worker import Worker
from toad.block_content import BlockContent
from toad.markdown_links import LinkContext
from toad.line_blocks import LineBlock
from toad.widgets.transcript_lines import (
    HorizontalRows, Lines, PlainLines, PreparedLines, TranscriptLinesRenderTask,
    link_place, selection_painted,
)


class ToolContent(HorizontalRows, BlockContent, Widget):
    """One live details widget painting the parts' canonical line blocks."""

    DEFAULT_CSS = "ToolContent { height: auto; overflow-x: auto; overflow-y: hidden; }"

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
        self._request_render()

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

    @property
    def line_sets(self) -> tuple[Lines, ...]:
        return (self._lines(self._width),) if self._width else ()

    def _request_render(self) -> None:
        if self._width and self.is_attached:
            self._render_worker = self.run_worker(
                self._render, group="tool-details", exclusive=True
            )

    async def _render(self) -> None:
        blocks, width, theme = self.blocks, self._width, self.app.colours.line_theme
        lines = await self.app.render_processes.submit(
            TranscriptLinesRenderTask(blocks, width, theme, await LinkContext.acquire(self))
        )
        if self.is_attached and (blocks, width, theme) == (self.blocks, self._width, self.app.colours.line_theme):
            previous_height = self._lines(width).height
            previous_width = self._lines(width).content_width
            self._styled = lines
            self.refresh(layout=(previous_height, previous_width) != (lines.height, lines.content_width))

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
        return selection_painted(self, self.on_background(strips[y]), y)

    def get_clipboard_text(self) -> str:
        return "\n".join(block.selection_text for block in self.blocks)
