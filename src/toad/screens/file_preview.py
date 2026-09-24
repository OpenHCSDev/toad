"""A read-only project file in the ordinary, closeable session tab bar."""

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from toad.screens.session_view import SessionView
from toad.widgets.footer import Footer
from toad.widgets.project_panel import FilePreview
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import TabHistoryControls


class FilePreviewScreen(SessionView, can_focus=False):
    AUTO_FOCUS = "FilePreview"
    BINDINGS = [
        Binding("escape", "back", "Previous tab", show=False),
        Binding("ctrl+w", "close_preview", "Close preview", show=False),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="file-preview-content"):
            with Horizontal(id="tab-navigation-header"):
                yield TabHistoryControls()
                yield SessionsTabs()
            yield FilePreview(self.path, id="file-preview")
        yield Footer(compact=True)

    async def action_back(self) -> None:
        if self.id is not None:
            await self.app.return_from_preview(self.id)

    async def action_close_preview(self) -> None:
        if self.id is not None:
            await self.app.close_session_mode(self.id)
