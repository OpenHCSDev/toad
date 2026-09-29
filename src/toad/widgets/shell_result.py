from __future__ import annotations
from toad.block_navigation import ConversationBlock

from textual.app import ComposeResult
from textual import containers
from textual.highlight import highlight
from textual.widgets import Static


from toad.widgets.non_selectable_label import NonSelectableLabel
from toad.widgets.committed_presentation import CheckpointBarrier


class ShellResult(ConversationBlock, CheckpointBarrier, containers.HorizontalGroup):
    def __init__(
        self,
        command: str,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        self._command = command
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)

    def compose(self) -> ComposeResult:
        yield NonSelectableLabel("$", id="prompt", markup=False)
        yield Static(highlight(self._command, language="sh"))

    def get_clipboard_text(self) -> str | None:
        return self._command
