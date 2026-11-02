"""Live and committed bodies draw worker-styled rows of their text, wrapped locally.

Text appends coalesce while styling; resizing never requests source styling.
"""

from __future__ import annotations

from textual.selection import Selection
from textual.widget import Widget

from toad.block_content import BlockContent
from toad.line_blocks import Body, MarkdownBody, LineBlock, LineRole, TextRole
from toad.widgets.linked_rows import ReferenceRendering
from toad.widgets.styled_rows import StyledRows


class LineMarkdown(StyledRows, ReferenceRendering, BlockContent, Widget):
    """Draw the declared body; selection copies the original source text."""

    DEFAULT_CSS = "LineMarkdown { height: auto; }"

    def __init__(self, text: str = "", *, role: type[LineRole] = TextRole,
                 bar: type[LineRole] | None = None, body: type[Body] = MarkdownBody,
                 id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.text = text
        self.role, self.bar, self.body_type = role, bar, body

    def line_blocks(self, text: str) -> tuple[LineBlock, ...]:
        """Semantic rows for this text; subclasses may add a final row."""
        return self.body_type(text, role=self.role, bar=self.bar).presentation()

    def styled_blocks(self) -> tuple[LineBlock, ...]:
        return self.line_blocks(self.text)

    @property
    def block(self) -> LineBlock:
        return self.line_blocks(self.text)[0]

    def get_clipboard_text(self) -> str | None:
        return self.text or None

    def update(self, text: str) -> None:
        """Replace the text; its rows arrive with the next render, without blocking."""
        if text != self.text:
            self.text = text
            self.restyle()

    def append(self, text: str) -> None:
        self.update(self.text + text)

    def get_selection(self, selection: Selection) -> tuple[str, str]:
        return selection.extract(self.text), "\n"
