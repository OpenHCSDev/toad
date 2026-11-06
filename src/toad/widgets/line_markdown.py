"""Live and committed bodies draw worker-styled rows of their text, wrapped locally.

Text appends coalesce while styling; resizing never requests source styling.
"""

from __future__ import annotations

from textual.widget import Widget

from toad.block_content import SelectsSource
from toad.line_blocks import Body, MarkdownBody, LineBlock, LineRole, NoBar, TextRole
from toad.native_style import AutoHeight
from toad.widgets.linked_rows import ReferenceRendering
from toad.widgets.styled_rows import StyledRows


class LineMarkdown(SelectsSource, AutoHeight, StyledRows, ReferenceRendering, Widget):
    """Draw the declared body; selection copies the original source text."""

    def __init__(self, text: str = "", *, role: type[LineRole] = TextRole,
                 bar: type[LineRole] = NoBar, body: type[Body] = MarkdownBody) -> None:
        super().__init__()
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

    def get_clipboard_text(self) -> str:
        return self.text

    def update(self, text: str) -> None:
        """Replace the text; its rows arrive with the next render, without blocking."""
        if text != self.text:
            self.text = text
            self.restyle()

    def append(self, text: str) -> None:
        self.update(self.text + text)
