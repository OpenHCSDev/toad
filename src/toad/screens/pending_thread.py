"""A lightweight, closeable thread tab shown before route discovery."""

from typing import cast
from pathlib import Path
from collections import deque
import asyncio
from weakref import ref

from textual import containers, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from toad import messages
from toad.app import ToadApp
from toad.screens.session_view import SessionView
from toad.session_tracker import SidebarState
from toad.widgets.channels_sidebar import ChannelsSlot
from toad.widgets.comms_sidebar import SelectTarget
from toad.widgets.conversation import ThreadLoading
from toad.workspace_chrome import NavigationSlot
from toad.widgets.side_bar import SideBar
from toad.navigation_target import NavigationContext, NavigationOwner


class PendingThreadScreen(SessionView, NavigationOwner, can_focus=False):
    """Display no unverified identity, transcript or read acknowledgement."""

    BINDINGS = [Binding("escape", "close_pending", "Cancel opening", show=False)]
    DEFAULT_CSS = "PendingThreadScreen > Center { height: 1fr; }"

    def __init__(self, *, owner_mode: str = "", project_path: Path = Path(), me: str = "") -> None:
        super().__init__()
        self.owner_mode = owner_mode
        self.project_path = project_path
        self.me = me
        self._thread_sidebar_state = SidebarState()
        self._channels = ChannelsSlot()

    def bind_navigation(self, context: NavigationContext) -> None:
        """Bind a prepared, never-presented shell to its one requested route."""
        if self._first_frame_presented:
            raise RuntimeError("A presented loading shell cannot be rebound")
        self.owner_mode = context.owner_mode
        self.project_path = context.project_path
        self.me = context.actor

    def channels_context(self) -> tuple[str, str]:
        return self.me, ""

    def compose(self) -> ComposeResult:
        yield NavigationSlot()
        with containers.Center():
            # This is the existing owner's cached channel projection, not the
            # unresolved destination. Shared hide/placement/scroll intent stays
            # visible without adding another wire read to route discovery.
            yield self._channels
            yield ThreadSidebar(
                SideBar.Panel("Thread", Static("Opening thread…")),
                right=True, hide=True, navigation=self._thread_sidebar_state,
                defer_mount=True,
            )
            with containers.Vertical(id="pending-thread-content"):
                yield ThreadLoading()

    @on(SelectTarget)
    async def on_select_target(self, event: SelectTarget) -> None:
        event.stop()
        await self.open_sidebar_target(event.target)

    @property
    def navigation_context(self) -> NavigationContext:
        return NavigationContext(cast(ToadApp, self.app), self.owner_mode, self.project_path, self.me)

    @on(messages.SessionCreate)
    def on_session_create(self, event: messages.SessionCreate) -> None:
        event.stop()
        self.app.post_message(messages.SessionCreate(self.owner_mode))

    async def action_close_pending(self) -> None:
        if self.id is not None:
            await cast(ToadApp, self.app).close_session_mode(self.id)


class PendingTabShells:
    """Bounded UI-only lookahead. No route/source work runs before selection."""

    def __init__(self, app: ToadApp, capacity: int) -> None:
        if type(capacity) is not int or capacity < 0:
            raise ValueError("Prepared tab capacity must be a non-negative integer")
        self._app = ref(app)
        self.capacity = capacity
        self._available: deque[PendingThreadScreen] = deque()
        self._preparing = False
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def app(self) -> ToadApp:
        app = self._app()
        if app is None:
            raise ReferenceError("The loading-shell owner has retired")
        return app

    def close(self) -> None:
        self._closed = True
        self._available.clear()

    def prepare(self) -> None:
        if (not self._closed and self.app.is_running and not self._preparing
                and len(self._available) < self.capacity):
            self._preparing = True
            self.app.run_worker(self._fill(), group="pending-tab-shells")

    async def _fill(self) -> None:
        try:
            while len(self._available) < self.capacity and self.app.is_running and not self._closed:
                async with self._lock:
                    if len(self._available) >= self.capacity:
                        return
                    screen = await self._create()
                    if not self._closed:
                        self._available.append(screen)
        finally:
            self._preparing = False

    async def _create(self) -> PendingThreadScreen:
        self.app._pending_thread_index += 1
        mode = f"pending-thread-{self.app._pending_thread_index}"
        screen = PendingThreadScreen()
        screen.id = mode
        self.app.add_mode(mode, lambda: screen)
        # Native mounting is asynchronous and does not select the mode. The
        # existing presentation boundary keeps its source callbacks dormant.
        await self.app._init_mode(mode)
        return screen

    async def acquire(self, context: NavigationContext) -> PendingThreadScreen:
        async with self._lock:
            screen = self._available.popleft() if self._available else await self._create()
        screen.bind_navigation(context)
        return screen
