from toad.core import input_events
from toad.core_event_carrier import CoreEventMessage
from toad.core import session_requests, events as core_events
from toad.core_event_carrier import CoreEventReceiver
import asyncio
from functools import partial
from pathlib import Path

from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.comms import Comms
from agent_comms.mro_dispatch import MroDispatch, handles
from textual import containers, getters, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.content import Content
from textual.events import ScreenResume
from textual.reactive import reactive, var
from textual.widget import Widget
from textual.widgets import (
    DirectoryTree,
    OptionList,
    Tree,
)

from toad import messages

from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.navigation_target import NavigationContext, NavigationOwner
from toad.screens.session_view import SessionView
from toad.session_tracker import SidebarState
from toad.widgets.comms_chat import resolve_session_thread, session_thread_name
from toad.widgets.comms_fork_dialog import ForkDialog
from toad.core.input_events import SelectTarget
from toad.widgets.comms_sidebar import CommsSidebar, CoordinationStatus
from toad.widgets.conversation import Conversation, ThreadLoading
from toad.widgets.footer import Footer
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.project_panel import ProjectPanel, ProjectSearchButton
from toad.widgets.recovery_view import RecoveryView
from toad.widgets.thread_comms import ThreadCommsSidebar
from toad.widgets.comms_chat import resolve_session_thread, session_thread_name
from toad.widgets.comms_fork_dialog import ForkDialog
from toad.core.input_events import SelectTarget
from toad.widgets.comms_sidebar import CoordinationStatus, CommsSidebar
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.navigation_target import NavigationContext, NavigationOwner
from toad.session_tracker import SidebarState
from toad.widgets.throbber import Throbber
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.navigation_target import FeedTarget, DirectTarget


class ModeProvider(Provider):
    async def search(self, query: str) -> Hits:
        """Search for Python files."""
        matcher = self.matcher(query)

        screen = self.screen.app.selected_session
        assert isinstance(screen, MainScreen)

        agent = screen.conversation.agent
        for mode in sorted(
            agent.available_modes if agent is not None else (), key=lambda mode: mode.name
        ):
            command = mode.name
            score = matcher.match(command)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(command),
                    partial(screen.conversation.set_mode, mode.id),
                    help=mode.description,
                )

    async def discover(self) -> Hits:
        screen = self.screen.app.selected_session
        assert isinstance(screen, MainScreen)

        agent = screen.conversation.agent
        for mode in sorted(
            agent.available_modes if agent is not None else (), key=lambda mode: mode.name
        ):
            yield DiscoveryHit(
                mode.name,
                partial(screen.conversation.set_mode, mode.id),
                help=mode.description,
            )


class MCPInventoryProvider(Provider):
    """Discover the optional static package inventory, not MCP authority."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        score = matcher.match("Pi MCP inventory")
        screen = self.screen.app.selected_session
        assert isinstance(screen, MainScreen)
        if score > 0:
            yield Hit(score, matcher.highlight("Pi MCP inventory"),
                      screen.action_mcp_inventory, help="Read-only package snapshot")

    async def discover(self) -> Hits:
        screen = self.screen.app.selected_session
        assert isinstance(screen, MainScreen)
        yield DiscoveryHit("Pi MCP inventory", screen.action_mcp_inventory,
                           help="Read-only package snapshot")


class MainScreen(CoreEventReceiver, SessionView, NavigationOwner, can_focus=False):
    footer_compact = True

    AUTO_FOCUS = "Conversation Prompt TextArea"

    CSS_PATH = "main.tcss"

    COMMANDS = {ModeProvider, MCPInventoryProvider}

    SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")
    BINDINGS = [
        Binding("ctrl+g", "toggle_irc", "IRC view"),
        Binding("ctrl+b,f20", "show_sidebar", "Sidebar"),
        Binding("ctrl+h", "go_home", "Home", show=False),
        Binding(
            "ctrl+left_square_bracket",
            "session_previous",
            "Previous session",
            group=SESSION_NAVIGATION_GROUP,
            show=False,
        ),
        Binding(
            "ctrl+right_square_bracket",
            "session_next",
            "Next session",
            group=SESSION_NAVIGATION_GROUP,
            show=False,
        ),
    ]

    BINDING_GROUP_TITLE = "Screen"
    busy_count = var(0)
    throbber: getters.query_one[Throbber] = getters.query_one("#throbber")
    conversation = getters.query_one(Conversation)
    @property
    def side_bar(self):
        return self.screen.query_one(ChannelsSidebar)
    project_directory_tree = getters.query_one("#project_directory_tree")

    column = reactive(False)
    column_width = reactive(100)
    scrollbar = reactive("")
    project_path: var[Path] = var(Path("./").expanduser().absolute())

    app = getters.app(ToadApp)

    def __init__(
        self,
        project_path: Path,
        agent: AgentDefinition | None = None,
        agent_session_id: str | None = None,
        session_pk: int | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()
        self.set_reactive(MainScreen.project_path, project_path)
        self._agent = agent
        self._agent_session_id = agent_session_id
        self.initial_coordination_root: str | None = None
        self._identity_wire: Comms | None = None
        self._comms_thread = (
            ""
            if agent is not None and agent.identity == "agent-comms.openhcs.dev"
            else session_thread_name(project_path)
        )
        self._session_pk = session_pk
        self._initial_prompt = initial_prompt
        self._thread_sidebar_state = SidebarState()
        self._project_panel: ProjectPanel | None = None
        self._content_loaded = agent is None
        self._content_loading = False
        self._content_ready = asyncio.Event()
        self._content_error: BaseException | None = None
        from toad.session_presentation import OperationalSessionPresentation

        self.presentation = OperationalSessionPresentation()

    async def prepare_presentation(self) -> None:
        from toad.widgets.session_thread_sidebar import SessionThreadSidebar

        await self.presentation.prepare(self)
        self._start_content_hydration()
        if sidebar := self.query_one_optional(SessionThreadSidebar):
            await sidebar.prepare_presentation()

    async def retire_presentation(self) -> None:
        from toad.widgets.session_thread_sidebar import SessionThreadSidebar

        if sidebar := self.query_one_optional(SessionThreadSidebar):
            await sidebar.retire_presentation()
        await self.presentation.retire(self)

    def retained_native_presentations(self):
        return ((self, self.presentation),) if self.presentation.widget is not None else ()

    def watch_title(self, title: str) -> None:
        self.app.terminal_attention.update()

    def get_loading_widget(self) -> Widget:
        return self.app.settings.ui.throbber.widget(self)

    def activate_session(self) -> None:
        from toad.widgets.comms_sidebar import CommsSidebar

        try:
            sidebar = self.query_one(CommsSidebar)
            # The identity is updated by ACP's coordination notification and
            # cached on this screen. Resolving it through the wire here can
            # block the first frame of every navigation on store I/O.
            sidebar.session_thread = self._comms_thread
        except Exception:
            pass
        # Hidden screens may defer sidebar geometry until they resume. Rebind
        # the header before the resumed screen's first paint, not on a timer.
        self._align_tabs_with_sidebar(False)
        if conversation := self.query_one_optional(Conversation):
            if watcher := conversation._directory_watcher:
                self.call_after_refresh(watcher.notify_if_visible)
        if self._project_panel is not None:
            self.call_after_refresh(self._project_panel.refresh_if_visible)

    def compose(self) -> ComposeResult:
        from toad.widgets.channels_sidebar import ChannelsSlot

        from toad.widgets.session_thread_sidebar import SessionThreadSidebar

        with containers.Center():
            yield SessionThreadSidebar(self)
            with containers.Vertical(id="session-content"):
                yield self.presentation.compose_content(self)
                if not self._content_loaded:
                    yield ThreadLoading(id="session-opening")

    def _make_conversation(self) -> Conversation:
        with self._context():
            return Conversation(
                self.project_path, self._agent, self._agent_session_id,
                self._session_pk, self.app.session_tracker.sessions[self.id].initial_title,
                initial_prompt=self._initial_prompt,
            )

    def _start_content_hydration(self) -> None:
        if (self.is_current and not self._content_loaded and not self._content_loading
                and self.is_attached):
            self._content_loading = True
            self.run_worker(self._load_content(), group="session-content")

    async def _load_content(self) -> None:
        try:
            for sidebar in self.query(SideBar):
                await sidebar.wait_content_ready()
            if not self.is_attached or self._closing:
                return
            content = self.query_one("#session-content", containers.Vertical)
            # The lifetime owner serializes initial activation and return.
            # Hydration must not construct a second rich view beside it.
            await self.presentation.prepare(self)
            conversation = self.query_one(Conversation)
            if not self.is_attached or self._closing:
                return
            self._content_loaded = True
            self.watch_column(self.column)
            self.watch_scrollbar("", self.scrollbar)
            conversation.display = True
            await content.query("#session-opening").remove()
            if self.is_current and self.screen.focused is None:
                conversation.focus_prompt()
        except BaseException as error:
            self._content_error = error
            raise
        finally:
            self._content_ready.set()

    async def wait_content_ready(self) -> None:
        await self._content_ready.wait()
        if self._content_error is not None and not self._closing and not self._closed:
            raise self._content_error

    async def close_presentation(self) -> None:
        self._content_ready.set()
        await self.presentation.close(self)

    def run_prompt(self, prompt: str) -> None:
        self.conversation

    def on_comms_session_named(self, thread_name: str) -> None:
        """Tell the sidebar which thread is this screen's session."""
        previous = self._comms_thread
        self._comms_thread = thread_name
        try:
            sidebar = self.query_one(CommsSidebar)
            sidebar.session_thread = thread_name
            sidebar.observation.refresh()
        except Exception:
            pass
        if self.id is not None:
            self.app.session_navigation.sync_identity(self.id, previous, thread_name)
            self.app.session_tracker.bind_identity(self.id, previous, thread_name)
        self._sync_thread_sidebar()
        if self.id is not None:
            self.app.session_navigation.sync_recovery(self.id, self.coordination_root)

    def _sync_thread_sidebar(self) -> None:
        """Bind a newly mounted right panel to the current session identity."""
        if status := self.query_one_optional(CoordinationStatus):
            status.set_thread(self._comms_thread)
        if recovery := self.query_one_optional(RecoveryView):
            recovery.set_identity(self._comms_thread, self.coordination_root)
        if comms_tree := self.query_one_optional(ThreadCommsSidebar):
            comms_tree.set_identity(self._comms_thread, self.coordination_root)
        from toad.widgets.context_explorer import ContextExplorer
        if context := self.query_one_optional(ContextExplorer):
            context.set_identity(self._comms_thread, self.coordination_root)

    @property
    def coordination_root(self) -> str | None:
        fact = self.app.coordination_facts.get(self)
        return fact.wire_root if fact is not None else self.initial_coordination_root

    def has_agent(self) -> bool:
        return self._agent is not None

    def spawn(self, *, project: Path | None = None, session_id: str | None = None,
              root: str | None = None) -> "MainScreen":
        """Create a peer of this native source through its actual declaration."""
        app = self.app
        with app._context():
            peer = MainScreen(project or self.project_path, self._agent, agent_session_id=session_id).data_bind(column=type(app).column,
                              column_width=type(app).column_width, scrollbar=type(app).scrollbar)
        peer.initial_coordination_root = root
        return peer

    @handles(core_events.CommsUpdated)
    async def on_comms_updated(self, event: CoreEventMessage) -> None:
        await ScreenCommsConsumer(self).dispatch(event.event.update)

    @handles(CoordinationChangedUpdate)
    async def on_coordination_update(self, event: CoordinationChangedUpdate) -> None:
        self.app.coordination_facts[self] = event
        if event.worktree is not None:
            project = Path(event.worktree)
            if project != self.project_path:
                self.project_path = project
                if self._project_panel is not None:
                    self._project_panel.path = project
                await self.conversation.sync_project_path(project)
                if self.id is not None:
                    self.app.session_navigation.sync_project(self.id, project)
        self.on_comms_session_named(event.thread.name)
        self.conversation.input_histories.bind_scope(f"thread:{event.thread.name}")

    _last_dm_target: str | None = None

    @property
    def _session_thread(self) -> str:
        return self._resolve_comms_thread()

    def _resolve_comms_thread(self) -> str:
        resolved: str | None
        try:
            from agent_comms.comms import wire

            from toad.comms_root import current_root, root_is_current

            if self.coordination_root is not None and not root_is_current(
                self.coordination_root
            ):
                raise ValueError("Comms route changed; this session retains its former wire")
            root_path = (
                Path(self.coordination_root).expanduser()
                if self.coordination_root is not None
                else current_root()
            )
            if self._identity_wire is None or self._identity_wire.root != root_path:
                shared = self.app.coordination_access.service
                self._identity_wire = shared if shared.root == root_path else wire(root_path)
            if self.coordination_root is not None:
                resolved = self._identity_wire.registry.require(self._comms_thread).name
            else:
                resolved = resolve_session_thread(
                    self._identity_wire, self.project_path, self._comms_thread
                )
        except Exception:
            resolved = None
        if resolved is not None:
            self._comms_thread = resolved
        return self._comms_thread

    @property
    def navigation_context(self) -> NavigationContext:
        assert self.id is not None
        return NavigationContext(self.app, self.id, self.project_path, self._comms_thread)

    def remember_direct_target(self, target: str) -> None:
        self._last_dm_target = target

    def action_mcp_inventory(self) -> None:
        """Open an inert package-owned snapshot; never locate a source checkout."""
        from toad.screens.mcp_inventory import MCPInventoryScreen

        self.app.push_screen(
            MCPInventoryScreen(
                self.project_path,
            )
        )

    async def action_toggle_irc(self) -> None:
        """Open the IRC feed as a native Toad session."""
        if self.id is not None:
            await self.open_sidebar_target(FeedTarget())

    async def action_toggle_dm(self) -> None:
        """Open the last-selected DM as a native Toad session."""
        target = self._last_dm_target
        if not target:
            try:
                sidebar = self.query_one(CommsSidebar)
            except Exception:
                return
            peers = [
                name
                for name in sorted(sidebar.observation.registry_names())
                if name != self._session_thread
            ]
            target = peers[0] if peers else ""
        if target and self.id is not None:
            await self.open_sidebar_target(DirectTarget(target))

    @handles(SelectTarget)
    async def on_comms_select_target(self, event: CoreEventMessage) -> None:
        """Open channels and DMs through Toad's native session modes."""
        await self.open_sidebar_target(event.event.target)

    def action_session_previous(self) -> None:
        if self.id is not None:
            self.app.session_navigation.events.publish(session_requests.SessionNavigate(self.id, -1))

    def action_session_next(self) -> None:
        if self.id is not None:
            self.app.session_navigation.events.publish(session_requests.SessionNavigate(self.id, +1))

    @handles(input_events.ProjectDirectoryUpdated)
    async def on_project_directory_update(self) -> None:
        if self._project_panel is not None:
            self._project_panel.invalidate()

    @on(DirectoryTree.FileSelected, "ProjectDirectoryTree")
    async def on_project_directory_tree_selected(self, event: Tree.NodeSelected):
        event.stop()
        if (data := event.node.data) is not None:
            await self.open_file_preview(data.path)

    @on(ProjectDirectoryTree.InsertSelected)
    def on_project_path_insert(
        self, event: ProjectDirectoryTree.InsertSelected
    ) -> None:
        event.stop()
        self.conversation.insert_path_into_prompt(event.path)

    @on(ProjectSearchButton.Requested)
    def on_project_search_requested(self, event: ProjectSearchButton.Requested) -> None:
        event.stop()
        self.conversation.prompt.path_search.focus()

    async def open_file_preview(self, path: Path) -> None:
        await self.app.session_navigation.preview(path)

    @handles(core_events.Plan)
    async def on_acp_plan(self, message: CoreEventMessage):
        from toad.widgets.session_thread_sidebar import SessionThreadSidebar

        self.query_one(SessionThreadSidebar).update_plan(message.event.entries)

    @handles(core_events.SessionTitleChanged)
    def on_session_title_changed(self, message: CoreEventMessage) -> None:
        if self.id is not None:
            self.app.session_tracker.update_session(self.id, title=message.event.name)

    @handles(core_events.SessionSubtitleChanged)
    def on_session_subtitle_changed(self, message: CoreEventMessage) -> None:
        if self.id is not None:
            self.app.session_tracker.update_session(self.id, subtitle=message.event.subtitle)

    @handles(core_events.SessionPathChanged)
    def on_session_path_changed(self, message: CoreEventMessage) -> None:
        if self.id is not None:
            self.app.session_tracker.update_session(self.id, path=message.event.path)


    def on_mount(self) -> None:
        # Route discovery already resolved new wire-thread identities off-loop.
        if sidebar := self.query_one_optional(CommsSidebar):
            sidebar.session_thread = (
                self._comms_thread
                if self.coordination_root is not None
                else self._resolve_comms_thread()
            )
        if self._content_loaded:
            self._content_ready.set()
        else:
            self.screen.frame_presentation.defer(self, self._start_content_hydration)
        self.observe_core(self.app.events)
        # Keep the screen-wide navigation row independent of sidebar geometry,
        # including when restoring a previously mounted owner tab.
        for tree in self.query("#project_directory_tree").results(DirectoryTree):
            tree.data_bind(path=MainScreen.project_path)
        for tree in self.query(DirectoryTree):
            tree.guide_depth = 3

    @handles(core_events.SidebarLayoutChanged)
    async def layout_observed(self, event: CoreEventMessage) -> None:
        self.screen.align_tabs_to_sidebars()

    def channels_context(self) -> tuple[str, str]:
        return self._comms_thread, ""

    @on(OptionList.OptionHighlighted)
    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option.id is not None:
            self.conversation.prompt.suggest(event.option.id)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "show_sidebar":
            sidebar = self.query_one_optional(ChannelsSidebar)
            if sidebar is None or sidebar.has_focus_within:
                return False
        return True

    def action_show_sidebar(self) -> None:
        self.side_bar.reveal()
        if title := self.side_bar.query_one_optional("SideBarCollapsible CollapsibleTitle"):
            title.focus()

    def action_focus_prompt(self) -> None:
        if conversation := self.query_one_optional(Conversation):
            conversation.focus_prompt()

    def sidebar_focus_target(self) -> Widget | None:
        conversation = self.query_one_optional(Conversation)
        if conversation is None or not self._content_loaded:
            return None
        target = conversation.prompt.prompt_text_area
        return target if target.focusable else None

    async def action_go_home(self) -> None:
        await self.app.select_session("store")

    @on(SideBar.Dismiss)
    def on_side_bar_dismiss(self, message: SideBar.Dismiss):
        message.stop()
        if conversation := self.query_one_optional(Conversation):
            conversation.focus_prompt(scroll_end=False)

    def watch_column(self, column: bool) -> None:
        if conversation := self.query_one_optional(Conversation):
            conversation.styles.max_width = max(10, self.column_width) if column else None

    def watch_column_width(self, column_width: int) -> None:
        self.watch_column(self.column)

    def watch_scrollbar(self, old_scrollbar: str, scrollbar: str) -> None:
        conversation = self.query_one_optional(Conversation)
        if conversation is None:
            return
        if old_scrollbar:
            conversation.remove_class(f"-scrollbar-{old_scrollbar}")
        if scrollbar:
            conversation.add_class(f"-scrollbar-{scrollbar}")


class ScreenCommsConsumer(MroDispatch):
    def __init__(self, screen):
        self.screen = screen

    @handles(CoordinationChangedUpdate)
    async def coordination_changed(self, update: CoordinationChangedUpdate):
        await self.screen.on_coordination_update(update)
