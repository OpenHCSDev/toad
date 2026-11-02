"""The shared line-block view for live tool details and permission previews."""
from textual.strip import Strip
from textual.widget import Widget
from toad.block_content import BlockContent
from toad.line_blocks import LineBlock
from toad.widgets.linked_rows import HorizontalRows, ReferenceRendering, selection_painted
from toad.widgets.styled_rows import StyledRows


class ToolContent(StyledRows, ReferenceRendering, HorizontalRows, BlockContent, Widget):
    """One live details widget painting the parts' canonical line blocks."""

    DEFAULT_CSS = "ToolContent { height: auto; overflow-x: auto; overflow-y: hidden; }"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.blocks: tuple[LineBlock, ...] = ()

    def styled_blocks(self) -> tuple[LineBlock, ...]:
        return self.blocks

    def update(self, blocks: tuple[LineBlock, ...]) -> None:
        if blocks != self.blocks:
            self.blocks = blocks
            self.restyle()

    def painted_row(self, strip: Strip, y: int) -> Strip:
        return selection_painted(self, strip, y)

    def get_clipboard_text(self) -> str:
        return "\n".join(block.selection_text for block in self.blocks)
