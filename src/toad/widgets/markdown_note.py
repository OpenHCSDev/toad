from textual.css.native import Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles
from ui_theme.scheme import ErrorColour

from toad.block_navigation import ConversationBlock
from toad.native_style import RightPadding, SidePadding
from toad.widgets.line_markdown import LineMarkdown


class MarkdownNote(RightPadding, ConversationBlock, LineMarkdown):
    """A note in the conversation, drawn as prepared lines like any response."""



class StopReasonNote(SidePadding, MarkdownNote):
    """Why a turn stopped early, framed in the error colour."""

    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("wide"), Variable(ErrorColour.name)),
    )

