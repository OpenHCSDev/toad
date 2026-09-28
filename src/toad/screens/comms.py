from toad.screens.session_view import SessionView
import asyncio
from pathlib import Path

from textual import containers, getters, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import ScreenResume
from textual.widget import Widget

from toad import messages
from toad.app import ToadApp
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.irc_message import SelectHistoricalIdentity
from toad.widgets.comms_sidebar import CoordinationStatus, CommsSidebar, SelectTarget
from toad.widgets.channels_sidebar import ChannelsSlot, ChannelsSidebar
from toad.session_tracker import SidebarState
from toad.workspace_chrome import FooterSlot, NavigationSlot
from toad.widgets.side_bar import SideBar
from toad.navigation_target import NavigationContext, NavigationOwner
from toad.widgets.recovery_view import RecoveryView
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import SideBar, ThreadSidebar, TabHistoryControls
from toad.navigation_target import FeedTarget, DirectTarget, NavigationContext, NavigationOwner
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar


class CommsScreen(SessionView, NavigationOwner, can_focus=False):
    """A channel or DM represented as a native concurrent Toad session."""

    AUTO_FOCUS = "CommsChatView Prompt TextArea"
    CSS_PATH = ["main.tcss", "comms.tcss"]
    SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")
    BINDINGS = [
        Binding("escape", "back_to_agent", "Agent session"),
        Binding("ctrl+h", "historical_sessions", "Saved sessions"),
        Binding("ctrl+g", "toggle_irc", "IRC view"),
        Binding("ctrl+b,f20", "show_sidebar", "Sidebar"),
        Binding("ctrl+t", "message_style", "IRC / Markdown"),
        Binding(
            "ctrl+left_square_bracket",
            "session_previous",
            "Previous session",
            group=SESSION_NAVIGATION_GROUP,
        ),
        Binding(
            "ctrl+right_square_bracket",
            "session_next",
            "Next session",
            group=SESSION_NAVIGATION_GROUP,
        ),
    ]

    def __init__(
        self,
        *,
        project_path: Path,
        owner_mode: str,
        me: str,
        target: str,
        kind: str,
        recovery_root: str | None = None,
        wire_root: str | None = None,
    ) -> None:
        super().__init__()
        self.project_path = project_path
        self.owner_mode = owner_mode
        self.me = me
        self.target = target
        self.kind = kind
        self.recovery_root = recovery_root
        self.wire_root = wire_root
        self._thread_sidebar_state = SidebarState()
        self._content_ready = asyncio.Event()
        self._content_error: BaseException | None = None
        self._content_loaded = False
        self._content_loading = False
        self._hydrate_queued = False
        self._sidebar_layout_watch = False

    app = getters.app(ToadApp)

    @property
    def coordination_root(self) -> str | None:
        return self.wire_root

    def channels_context(self) -> tuple[str, str]:
        return self.me, self.target

    def compose(self) -> ComposeResult:
        yield NavigationSlot()
        with containers.Center():
            yield ChannelsSlot()
            yield ThreadSidebar(
                SideBar.Panel(
                    "Connection",
                    CoordinationStatus(self.me),
                    id="coordination-panel",
                ),
                SideBar.Panel("Recovery", RecoveryView(self.me, wire_root=self.recovery_root), collapsed=True,
                              id="recovery-panel"),
                SideBar.Panel("Comms", ThreadCommsSidebar(
                    self.me, wire_root=self.recovery_root, live=True),
                    id="thread-comms-panel", header_control=RelationshipSort()),
                right=True, hide=True, navigation=self._thread_sidebar_state,
            )
            with containers.Vertical(id="comms-content"):
                yield Button("Saved sessions", id="historical-sessions")
                if not self._content_loaded:
                    yield Static(f"Opening {self.target}…", id="comms-opening")
                else:
                    yield CommsChatView(
                        self.project_path,
                        me=self.me,
                        target=self.target,
                        kind=self.kind,
                        wire_root=self.wire_root,
                    )
        yield FooterSlot()

    @on(SelectHistoricalIdentity)
    async def select_historical_identity(self, event: SelectHistoricalIdentity) -> None:
        event.stop()
        from toad.screens.historical_sessions import HistoricalSessions
        comms = self.app.coordination_wire
        threads = await asyncio.to_thread(comms.views.historical_threads, event.name)
        if not threads:
            self.notify("This sender has no preserved identity declaration.")
            return
        self.app.push_screen(HistoricalSessions(comms, threads, name=event.name, source=event.source))

    @on(Button.Pressed, "#historical-sessions")
    async def action_historical_sessions(self) -> None:
        from toad.screens.historical_sessions import HistoricalSessions
        comms = self.app.coordination_wire
        threads = await asyncio.to_thread(comms.views.historical_threads)
        if not threads:
            self.notify("No preserved history sources are attached yet.")
            return
        self.app.push_screen(HistoricalSessions(comms, threads,
            name=self.target if self.kind == "dm" else None))

    def on_mount(self) -> None:
        if not self._content_loaded:
            self.call_after_first_frame(self, self._start_hydration)
            return
        self._prepare_content()

    def _start_hydration(self) -> None:
        """Only a written route frame may start conversation composition."""
        if not self._content_loaded and not self._hydrate_queued:
            self._hydrate_queued = True
            self.call_later(self._load_content)

    def _prepare_content(self) -> None:
        for sidebar in self.query(SideBar):
            sidebar._apply_layout()
        if not self._sidebar_layout_watch:
            self._sidebar_layout_watch = True
            self.app.sidebar_layout_changed.subscribe(
                self, lambda _event: self.align_tabs_to_sidebars()
            )
        self.align_tabs_to_sidebars()
        chat = self.query_one(CommsChatView)
        chat._me = self.me
        chat.project_path = self.project_path
        # Shared navigation may already belong to another tab when hydration
        # finishes. Its actor/target are bound by the mode transition owner.
        self.query_one(CoordinationStatus).set_thread(self.me)
        chat.prepare_prompt()

    async def _load_content(self) -> None:
        if self._content_loading or not self.is_attached:
            return
        self._content_loading = True
        self._content_loaded = True
        try:
            # The navigation/sidebar shell is already visible in its chosen
            # state. Hydrate only the conversation; retain those exact controls
            # and their scroll position throughout the opening transition.
            with self.app.batch_update():
                content = self.query_one("#comms-content", containers.Vertical)
                await content.remove_children()
                await content.mount(CommsChatView(
                    self.project_path, me=self.me, target=self.target, kind=self.kind,
                ))
                if self.is_attached:
                    self._prepare_content()
                    if self.is_current:
                        await self.prepare_navigation()
                        await self.layout_navigation()
        except BaseException as error:
            self._content_error = error
            raise
        finally:
            self._content_ready.set()

    async def wait_content_ready(self) -> None:
        await self._content_ready.wait()
        if self._content_error is not None:
            raise self._content_error

    async def prepare_navigation(self) -> None:
        # A tab switch must not wait on the writer lock. The mounted chat's
        # asynchronous history refresh marks its displayed cursor as read.
        await super().prepare_navigation()

    def _on_screen_resume(self, event: ScreenResume) -> None:
        self.align_tabs_to_sidebars()
        if chat := self.query_one_optional(CommsChatView):
            self.call_after_refresh(chat.prepare_prompt)

    async def action_message_style(self) -> None:
        if chat := self.query_one_optional(CommsChatView):
            await chat.toggle_message_style()

    def action_focus_prompt(self) -> None:
        if chat := self.query_one_optional(CommsChatView):
            chat.prepare_prompt()

    def sidebar_focus_target(self) -> Widget | None:
        if chat := self.query_one_optional(CommsChatView):
            target = chat.prompt.prompt_text_area
            return target if target.focusable else None
        return None

    def action_show_sidebar(self) -> None:
        sidebar = self.query_one(ChannelsSidebar)
        sidebar.reveal()
        sidebar.query_one("SideBarCollapsible CollapsibleTitle").focus()

    @on(SideBar.Dismiss)
    def on_side_bar_dismiss(self, event: SideBar.Dismiss) -> None:
        event.stop()
        self.action_focus_prompt()

    @property
    def navigation_context(self) -> NavigationContext:
        return NavigationContext(self.app, self.owner_mode, self.project_path, self.me)

    @on(SelectTarget)
    async def on_select_target(self, event: SelectTarget) -> None:
        await self.open_sidebar_target(event.target)

    async def action_back_to_agent(self) -> None:
        if self.app.session_tracker.get_session(self.owner_mode) is None:
            await self.app.switch_mode("store")
        else:
            await self.app.switch_mode(self.owner_mode)

    async def action_toggle_irc(self) -> None:
        if self.kind == "irc":
            await self.action_back_to_agent()
        else:
            await self.open_sidebar_target(FeedTarget())

    async def action_toggle_dm(self) -> None:
        if self.kind == "dm":
            await self.action_back_to_agent()
            return
        sidebar = self.query_one(CommsSidebar)
        peers = [
            name for name in sorted(sidebar._comms_registry_names()) if name != self.me
        ]
        if peers:
            await self.open_sidebar_target(DirectTarget(peers[0]))

    def action_session_previous(self) -> None:
        self.post_message(messages.SessionNavigate(self.owner_mode, -1))

    def action_session_next(self) -> None:
        self.post_message(messages.SessionNavigate(self.owner_mode, +1))

    async def action_close_session(self) -> None:
        if self.id is not None:
            await self.app.close_session_mode(self.id)
