from agent_comms.mro_dispatch import handles
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from toad.core import events as core_events
from toad.core import session_requests
from toad.screens.session_view import SessionView
import asyncio
from pathlib import Path

from textual import containers, getters, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import ScreenResume
from textual.widget import Widget
from textual.worker import WorkerCancelled
from textual.widgets import Button, Static

from toad import messages
from toad.conversation_kind import ConversationKind
from toad.app import ToadApp
from toad.widgets.comms_chat import CommsChatView
from toad.core.input_events import SelectHistoricalIdentity
from toad.core.input_events import SelectTarget
from toad.widgets.comms_sidebar import CoordinationStatus, CommsSidebar
from toad.widgets.channels_sidebar import ChannelsSlot, ChannelsSidebar
from toad.session_tracker import SidebarState
from toad.widgets.side_bar import SideBar
from toad.navigation_target import NavigationContext, NavigationOwner
from toad.widgets.recovery_view import RecoveryView
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import SideBar, ThreadSidebar, TabHistoryControls
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar


class CommsScreen(CoreEventReceiver, SessionView, NavigationOwner, can_focus=False):
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
        kind: type[ConversationKind],
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

    app = getters.app(ToadApp)

    @property
    def coordination_root(self) -> str | None:
        return self.wire_root

    def relationship_context(self) -> tuple[str, str | None]:
        return self.me, self.recovery_root

    def rebind_identity(self, identity: str) -> None:
        self.me = identity
        if chat := self.query_one_optional(CommsChatView):
            chat._me = identity
        if sidebar := self.query_one_optional(CommsSidebar):
            sidebar.session_thread = identity
        if status := self.query_one_optional(CoordinationStatus):
            status.set_thread(identity)
        if recovery := self.query_one_optional(RecoveryView):
            recovery.set_identity(identity, self.recovery_root)

    def rebind_recovery(self, root: str | None) -> None:
        self.recovery_root = root
        if recovery := self.query_one_optional(RecoveryView):
            recovery.set_identity(self.me, root)

    def rebind_project(self, project: Path) -> None:
        self.project_path = project
        if chat := self.query_one_optional(CommsChatView):
            chat.project_path = project
            chat.working_directory = str(project)

    def channels_context(self) -> tuple[str, str]:
        return self.me, self.target

    def compose(self) -> ComposeResult:
        with containers.Center():
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
                with containers.Vertical(id="comms-chat-content"):
                    if not self._content_loaded:
                        yield Static(f"Opening {self.target}…", id="comms-opening")
                    else:
                        yield self.create_chat()

    def create_chat(self) -> CommsChatView:
        """One route-bound conversation factory for compose and lazy hydration."""
        return CommsChatView(
            self.project_path, me=self.me, target=self.target, kind=self.kind,
            wire_root=self.wire_root,
        )


    @handles(SelectHistoricalIdentity)
    async def select_historical_identity(self, event: CoreEventMessage) -> None:
        event.stop()
        from toad.screens.historical_sessions import HistoricalSessions
        comms = self.app.coordination_access.service
        threads = await asyncio.to_thread(comms.views.historical_threads, event.event.name)
        if not threads:
            self.notify("This sender has no preserved identity declaration.")
            return
        self.app.push_screen(HistoricalSessions(comms, threads, name=event.event.name, source=event.event.source))

    @on(Button.Pressed, "#historical-sessions")
    async def action_historical_sessions(self) -> None:
        from toad.screens.historical_sessions import HistoricalSessions
        comms = self.app.coordination_access.service
        threads = await asyncio.to_thread(comms.views.historical_threads)
        if not threads:
            self.notify("No preserved history sources are attached yet.")
            return
        self.app.push_screen(HistoricalSessions(comms, threads,
            name=self.kind.historical_thread(self.target)))

    def on_mount(self) -> None:
        if not self._content_loaded:
            self.screen.frame_presentation.defer(self, self._start_hydration)
            return
        self._prepare_content()

    def _start_hydration(self) -> None:
        """Only a written route frame may start conversation composition."""
        if not self._content_loaded:
            self.run_worker(self._load_content, group="comms-content")

    def _prepare_content(self) -> None:
        self.app.workspace_chrome.layout_sidebars(self.screen)
        self.observe_core(self.app.events)
        self.screen.align_tabs_to_sidebars()
        chat = self.query_one(CommsChatView)
        chat._me = self.me
        chat.project_path = self.project_path
        # Shared navigation may already belong to another tab when hydration
        # finishes. Its actor/target are bound by the mode transition owner.
        self.query_one(CoordinationStatus).set_thread(self.me)
        chat.prepare_prompt()

    @handles(core_events.SidebarLayoutChanged)
    async def layout_observed(self, event: CoreEventMessage) -> None:
        self.screen.align_tabs_to_sidebars()

    async def _load_content(self) -> None:
        if self._content_loaded or not self.is_attached:
            return
        self._content_loaded = True
        try:
            # The navigation/sidebar shell is already visible in its chosen
            # state. Hydrate only the conversation; retain those exact controls
            # and their scroll position throughout the opening transition.
            content = self.query_one("#comms-chat-content", containers.Vertical)
            await content.remove_children()
            await content.mount(self.create_chat())
            if self.is_attached:
                self._prepare_content()
                if self.is_current:
                    await self.screen.prepare_navigation()
                    await self.screen.layout_navigation()
        except BaseException as error:
            self._content_error = error
            raise
        finally:
            self._content_ready.set()

    async def wait_content_ready(self) -> None:
        await self._content_ready.wait()
        if self._content_error is not None:
            raise self._content_error

    async def close_presentation(self) -> None:
        """Join hydration before its controls or input pump are pruned."""
        for worker in self.workers.cancel_group(self, "comms-content"):
            try:
                await worker.wait()
            except WorkerCancelled as error:
                self._content_error = error
        self._content_ready.set()

    async def on_unmount(self) -> None:
        await self.close_presentation()


    def activate_session(self) -> None:
        self.screen.align_tabs_to_sidebars()
        if chat := self.query_one_optional(CommsChatView):
            self.call_after_refresh(chat.prepare_prompt)

    async def action_message_style(self) -> None:
        if chat := self.query_one_optional(CommsChatView):
            await chat.message_history.toggle_style()

    def action_focus_prompt(self) -> None:
        if chat := self.query_one_optional(CommsChatView):
            chat.prepare_prompt()

    def sidebar_focus_target(self) -> Widget | None:
        if chat := self.query_one_optional(CommsChatView):
            target = chat.prompt.prompt_text_area
            return target if target.focusable else None
        return None

    def action_show_sidebar(self) -> None:
        sidebar = self.screen.query_one(ChannelsSidebar)
        sidebar.reveal()
        sidebar.query_one("SideBarCollapsible CollapsibleTitle").focus()

    @on(SideBar.Dismiss)
    def on_side_bar_dismiss(self, event: SideBar.Dismiss) -> None:
        event.stop()
        self.action_focus_prompt()

    @property
    def navigation_context(self) -> NavigationContext:
        return NavigationContext(self.app, self.owner_mode, self.project_path, self.me)

    @handles(SelectTarget)
    async def on_select_target(self, event: CoreEventMessage) -> None:
        await self.open_sidebar_target(event.event.target)

    async def action_back_to_agent(self) -> None:
        if self.app.session_tracker.get_session(self.owner_mode) is None:
            await self.app.select_session("store")
        else:
            await self.app.select_session(self.owner_mode)

    async def action_toggle_irc(self) -> None:
        await self.kind.toggle_irc(self)

    async def action_toggle_dm(self) -> None:
        await self.kind.toggle_dm(self)

    def action_session_previous(self) -> None:
        self.app.session_navigation.events.publish(session_requests.SessionNavigate(self.owner_mode, -1))

    def action_session_next(self) -> None:
        self.app.session_navigation.events.publish(session_requests.SessionNavigate(self.owner_mode, +1))

    async def action_close_session(self) -> None:
        if self.id is not None:
            await self.app.session_navigation.close(self.id)
