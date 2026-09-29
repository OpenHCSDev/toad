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
        for part in self.parts:
            yield from part.compose(self)
