"""A lightweight, closeable thread tab shown before route discovery."""

from typing import cast
from pathlib import Path

from textual import containers, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from toad import messages
from toad.app import ToadApp
from toad.screens.session_view import SessionView
from toad.session_tracker import SidebarState
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.comms_sidebar import CommsSidebar, SelectTarget
from toad.widgets.conversation import ThreadLoading
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import SideBar, TabHistoryControls


class PendingThreadScreen(SessionView, can_focus=False):
    """Display no unverified identity, transcript or read acknowledgement."""

    BINDINGS = [Binding("escape", "close_pending", "Cancel opening", show=False)]
    DEFAULT_CSS = "PendingThreadScreen > Center { height: 1fr; }"

    def __init__(self, *, owner_mode: str, project_path: Path, me: str) -> None:
        super().__init__()
        self.owner_mode = owner_mode
        self.project_path = project_path
        self.me = me
        self._thread_sidebar_state = SidebarState()

    def compose(self) -> ComposeResult:
        with containers.Horizontal(id="tab-navigation-header"):
            yield TabHistoryControls()
            yield SessionsTabs()
        with containers.Center():
            # This is the existing owner's cached channel projection, not the
            # unresolved destination. Shared hide/placement/scroll intent stays
            # visible without adding another wire read to route discovery.
            yield ChannelsSidebar(self.me, observe=False)
            yield SideBar(
                SideBar.Panel("Thread", Static("Opening thread…")),
                id="thread-sidebar", right=True, hide=True, navigation=self._thread_sidebar_state,
            )
            with containers.Vertical(id="pending-thread-content"):
                yield ThreadLoading()

    @on(SelectTarget)
    async def on_select_target(self, event: SelectTarget) -> None:
        event.stop()
        await cast(ToadApp, self.app).open_comms_session(
            owner_mode=self.owner_mode, project_path=self.project_path,
            me=self.me, target=event.target, kind=event.kind,
        )

    @on(messages.SessionCreate)
    def on_session_create(self, event: messages.SessionCreate) -> None:
        event.stop()
        self.app.post_message(messages.SessionCreate(self.owner_mode))

    @on(CommsSidebar.ThreadAction)
    def on_thread_action(self, event: CommsSidebar.ThreadAction) -> None:
        if event.action == "comms_fork":
            event.stop()
            if owner := cast(ToadApp, self.app)._main_session_screen(self.owner_mode):
                owner.post_message(CommsSidebar.ThreadAction(event.name, event.action))

    async def action_close_pending(self) -> None:
        if self.id is not None:
            await cast(ToadApp, self.app).close_session_mode(self.id)
