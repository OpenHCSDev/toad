from textual import containers
from textual.app import ComposeResult
from toad.tool_output import ToolOutputPart


class ACPToolCallContent(containers.VerticalGroup):

    def __init__(
        self,
        content: tuple[ToolOutputPart, ...],
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.parts = content
        super().__init__(id=id, classes=classes)

    def compose(self) -> ComposeResult:
        from toad.widgets.tool_content import ToolContent

        content = ToolContent()
        content.update(tuple(block for part in self.parts for block in part.line_blocks))
        yield content
