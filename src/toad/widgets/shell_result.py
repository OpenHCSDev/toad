from __future__ import annotations
from toad.block_navigation import ConversationBlock

from textual.app import ComposeResult
from textual import containers
from textual.css.native import Keyword, NativeDeclaration, Percent, Variable
from textual.css.styles import Styles
from textual.highlight import highlight
from textual.widgets import Static
from ui_theme.scheme import ForegroundColour, PrimaryColour


from toad.native_style import PrimaryText, RightMargin
from toad.widgets.non_selectable_label import NonSelectableLabel
from toad.widgets.committed_presentation import CommitBarrier
from toad.shell_output import ShellCommandOutput


class ShellPrompt(RightMargin, PrimaryText, NonSelectableLabel):
    """The `$` before a shell command."""




class ShellResult(ConversationBlock, CommitBarrier, containers.HorizontalGroup):
    native_theme = (
        NativeDeclaration.of(Styles.border_left, Keyword("blank"), Variable(PrimaryColour.name)),
        NativeDeclaration.of(Styles.background, Variable(ForegroundColour.name), Percent(4)),
    )

    def __init__(
        self,
        source: ShellCommandOutput,
        *,
        disabled: bool = False,
    ) -> None:
        self.source = source
        super().__init__(disabled=disabled)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (1, 0)
        self.styles.margin = (1, 1, 1, 0)

    def compose(self) -> ComposeResult:
        yield ShellPrompt("$", markup=False)
        yield Static(highlight(self.source.command, language="sh"))

    def get_clipboard_text(self) -> str:
        return self.source.command
