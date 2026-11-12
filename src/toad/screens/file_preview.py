"""A read-only project file in the ordinary, closeable session tab bar."""

from pathlib import Path
from collections.abc import Callable

from textual.app import ComposeResult
from toad.column_layout import ColumnLayout
from toad.configured_view import ConfiguredView
from toad.session_actions import ReturnToViewAction, CloseViewAction
from textual.containers import Horizontal, Vertical
from toad.screens.session_view import SessionBody, SessionContents, SessionView
from textual.widget import Widget
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import TabHistoryControls


class FileContents(ColumnLayout, SessionContents):
    def apply_layout_preferences(self):
        super().apply_layout_preferences()
        self.apply_column_layout()


class FilePreviewScreen(ConfiguredView, SessionView, can_focus=False, actions=(ReturnToViewAction, CloseViewAction)):
    footer_compact = True

    # FilePreview scrolls in its body (1325acc3), so the body takes focus and the close key.
    AUTO_FOCUS = "TextArea, FilePreview > VerticalScroll"
    def __init__(self, path: Path, content: Callable[[], Widget]) -> None:
        super().__init__(name=path.name)
        self.project_path = path.parent
        self.preview = content()

    @property
    def project_root(self) -> Path:
        return self.project_path

    def compose(self) -> ComposeResult:
        with SessionBody():
            with FileContents():
                yield self.preview
