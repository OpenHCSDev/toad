from textual.css.native import Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.widgets import Static
from ui_theme.scheme import ErrorColour

from toad.block_navigation import SeparatedBlock
from toad.entry_placement import ChronologicalEntry
from toad.native_style import RightPadding


class Note(RightPadding, SeparatedBlock, Static):

    def get_clipboard_text(self) -> str:
        return str(self.render())


class ErrorNote(ChronologicalEntry, Note):
    """A note reporting an error, framed in the error colour."""

    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("heavy"), Variable(ErrorColour.name)),
    )
