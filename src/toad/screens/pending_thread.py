"""A lightweight, closeable thread tab shown before route discovery."""

from typing import cast

from textual import containers
from textual.app import ComposeResult
from textual.binding import Binding

from toad.app import ToadApp
from toad.screens.session_view import SessionView
from toad.widgets.conversation import ThreadLoading
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import TabHistoryControls


class PendingThreadScreen(SessionView, can_focus=False):
    """Display no unverified identity, transcript or read acknowledgement."""

    BINDINGS = [Binding("escape", "close_pending", "Cancel opening", show=False)]

    def compose(self) -> ComposeResult:
        with containers.Horizontal(id="tab-navigation-header"):
            yield TabHistoryControls()
            yield SessionsTabs()
        with containers.Vertical(id="pending-thread-content"):
            yield ThreadLoading()

    async def action_close_pending(self) -> None:
        if self.id is not None:
            await cast(ToadApp, self.app).close_session_mode(self.id)
