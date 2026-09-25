import asyncio
from pathlib import Path

from textual import containers, getters, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import ScreenResume
from textual.screen import Screen
from textual.widgets import Static
from toad.widgets.footer import Footer

from toad import messages
from toad.constants import ALL_COMMS_TARGET
from toad.app import ToadApp
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_fork_dialog import ForkDialog
from toad.widgets.comms_sidebar import CoordinationStatus, CommsSidebar, SelectTarget
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.session_tracker import SidebarState
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import SideBar, TabHistoryControls
from toad.widgets.recovery_view import RecoveryView
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar
from toad.screens.session_view import SessionView


class CommsScreen(SessionView, can_focus=False):
    """A channel or DM represented as a native concurrent Toad session."""

    AUTO_FOCUS = "CommsChatView Prompt TextArea"
    CSS_PATH = ["main.tcss", "comms.tcss"]
    SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")
    BINDINGS = [
        Binding("escape", "back_to_agent", "Agent session"),
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
    ) -> None:
        super().__init__()
        self.project_path = project_path
        self.owner_mode = owner_mode
        self.me = me
        self.target = target
        self.kind = kind
        self.recovery_root = recovery_root
        self._thread_sidebar_state = SidebarState()
        self._content_ready = asyncio.Event()
        self._content_error: BaseException | None = None
        self._content_loaded = False
        self._content_loading = False
        self._hydrate_queued = False
        self._flush_queued = False
        self._sidebar_layout_watch = False

    app = getters.app(ToadApp)

    def compose(self) -> ComposeResult:
        with containers.Horizontal(id="tab-navigation-header"):
            yield TabHistoryControls()
            yield SessionsTabs()
        with containers.Center():
            yield ChannelsSidebar(self.me, self.target)
            yield SideBar(
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
                id="thread-sidebar", right=True, hide=True, navigation=self._thread_sidebar_state,
            )
            with containers.Vertical(id="comms-content"):
                if not self._content_loaded:
                    yield Static(f"Opening {self.target}…", id="comms-opening")
                else:
                    yield CommsChatView(
                        self.project_path,
                        me=self.me,
                        target=self.target,
                        kind=self.kind,
                    )
        yield Footer()

    def on_mount(self) -> None:
        if not self._content_loaded:
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
            self.watch(
                self.query_one("#channels-sidebar", SideBar), "collapsed",
                lambda _collapsed: self.align_tabs_to_sidebars(),
            )
            self.app.sidebar_layout_changed.subscribe(
                self, lambda _event: self.align_tabs_to_sidebars()
            )
        self.align_tabs_to_sidebars()
        chat = self.query_one(CommsChatView)
        chat._me = self.me
        chat.project_path = self.project_path
        self.query_one(CommsSidebar).session_thread = self.me
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

    def action_show_sidebar(self) -> None:
        sidebar = self.query_one(SideBar)
        sidebar.reveal()
        sidebar.query_one("SideBarCollapsible CollapsibleTitle").focus()

    @on(SideBar.Dismiss)
    def on_side_bar_dismiss(self, event: SideBar.Dismiss) -> None:
        event.stop()
        self.action_focus_prompt()

    async def _open(self, target: str, kind: str) -> None:
        await self.app.open_comms_session(
            owner_mode=self.owner_mode,
            project_path=self.project_path,
            me=self.me,
            target=target,
            kind=kind,
        )

    @on(SelectTarget)
    async def on_select_target(self, event: SelectTarget) -> None:
        if event.kind == "session":
            await self.action_back_to_agent()
        else:
            await self._open(event.target, event.kind)

    async def action_back_to_agent(self) -> None:
        if self.app.session_tracker.get_session(self.owner_mode) is None:
            await self.app.switch_mode("store")
        else:
            await self.app.switch_mode(self.owner_mode)

    async def action_toggle_irc(self) -> None:
        if self.kind == "irc":
            await self.action_back_to_agent()
        else:
            await self._open(ALL_COMMS_TARGET, "irc")

    async def action_toggle_dm(self) -> None:
        if self.kind == "dm":
            await self.action_back_to_agent()
            return
        sidebar = self.query_one(CommsSidebar)
        peers = [
            name for name in sorted(sidebar._comms_registry_names()) if name != self.me
        ]
        if peers:
            await self._open(peers[0], "dm")

    def action_session_previous(self) -> None:
        self.post_message(messages.SessionNavigate(self.owner_mode, -1))

    def action_session_next(self) -> None:
        self.post_message(messages.SessionNavigate(self.owner_mode, +1))

    async def action_close_session(self) -> None:
        if self.id is not None:
            await self.app.close_session_mode(self.id)

    @on(CommsSidebar.ThreadAction)
    async def on_thread_action(self, event: CommsSidebar.ThreadAction) -> None:
        if event.action != "comms_fork":
            return
        parent = event.name

        def do_fork(spec: tuple[str, str] | None) -> None:
            if not spec:
                return
            import os

            from agent_comms import invoke_context_tool
            from agent_comms.operations import wire

            root = os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")
            try:
                invoke_context_tool(
                    wire(root),
                    event.action,
                    subject=parent,
                    arguments={"name": spec[0], "task": spec[1]},
                )
                self.notify(f"forked {spec[0]} from {parent}", title="Comms")
            except Exception as error:
                self.notify(str(error), title="Comms fork failed", severity="error")

        self.app.push_screen(ForkDialog(parent), do_fork)
