from textual import containers
from textual.app import ComposeResult
from toad.tool_output import ToolOutputPart
from toad.widgets.tool_content import ToolContent


class ACPToolCallContent(containers.VerticalGroup):

    def __init__(
        self,
        content: tuple[ToolOutputPart, ...],
    ) -> None:
        self.parts = content
        super().__init__()

    def compose(self) -> ComposeResult:

        content = ToolContent()
        content.update(tuple(block for part in self.parts for block in part.line_blocks))
        yield content
