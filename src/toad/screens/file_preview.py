"""A read-only project file in the ordinary, closeable session tab bar."""

from pathlib import Path
from collections.abc import Callable

from textual.app import ComposeResult
from textual.document._editing import EditingMode
from toad.widget_actions import WidgetAction
from textual.containers import Horizontal, Vertical
from toad.screens.session_view import SessionView
from textual.widget import Widget
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import TabHistoryControls


class PreviewNavigationAction(WidgetAction, declared_name=None):
    def available(self, context):
        return context.id is not None


class PreviousPreviewAction(PreviewNavigationAction):
    """Return from the file preview to the previously selected tab."""
    keys = {EditingMode: ("escape",)}

    async def apply(self, context):
        await context.app.session_navigation.return_from(context.id)


class ClosePreviewAction(PreviewNavigationAction):
    """Close this file preview."""
    keys = {EditingMode: ("ctrl+w",)}
    priority = True

    async def apply(self, context):
        await context.app.session_navigation.close(context.id)


class FilePreviewScreen(SessionView, can_focus=False, actions=(PreviewNavigationAction,)):
    footer_compact = True
    shows_channels = False

    # FilePreview scrolls in its body (1325acc3), so the body takes focus and the close key.
    AUTO_FOCUS = "TextArea, FilePreview > VerticalScroll"
    def __init__(self, path: Path, content: Callable[[], Widget]) -> None:
        super().__init__(name=path.name)
        self.project_path = path.parent
        self.preview = content()

    def compose(self) -> ComposeResult:
        with Vertical(id="file-preview-content"):
            yield self.preview
