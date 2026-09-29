"""A read-only project file in the ordinary, closeable session tab bar."""

from pathlib import Path
from typing import cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from toad.screens.session_view import SessionView
from toad.widgets.footer import Footer
from toad.widgets.acp_log import file_preview
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import TabHistoryControls


class FilePreviewScreen(SessionView, can_focus=False):
    footer_compact = True
    shows_channels = False

    AUTO_FOCUS = "TextArea, FilePreview"
    BINDINGS = [
        Binding("escape", "back", "Previous tab", show=False),
        Binding("ctrl+w", "close_preview", "Close preview", show=False, priority=True),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__(name=path.name)
        self.project_path = path.parent

    def compose(self) -> ComposeResult:
        with Vertical(id="file-preview-content"):
            yield file_preview(self.project_path / cast(str, self.name))

    async def action_back(self) -> None:
        if self.id is not None:
            await self.app.return_from_preview(self.id)

    async def action_close_preview(self) -> None:
        if self.id is not None:
            await self.app.close_session_mode(self.id)
