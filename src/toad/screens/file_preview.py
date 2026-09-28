"""A read-only project file in the ordinary, closeable session tab bar."""

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from toad.screens.session_view import SessionView
from toad.workspace_chrome import FooterSlot, NavigationSlot
from toad.widgets.acp_log import file_preview


class FilePreviewScreen(SessionView, can_focus=False):
    AUTO_FOCUS = "TextArea, FilePreview"
    BINDINGS = [
        Binding("escape", "back", "Previous tab", show=False),
        Binding("ctrl+w", "close_preview", "Close preview", show=False, priority=True),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="file-preview-content"):
            yield NavigationSlot()
            yield file_preview(self.path)
        yield FooterSlot(compact=True)

    async def action_back(self) -> None:
        if self.id is not None:
            await self.app.return_from_preview(self.id)

    async def action_close_preview(self) -> None:
        if self.id is not None:
            await self.app.close_session_mode(self.id)
