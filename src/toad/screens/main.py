from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.mro_dispatch import MroDispatch, handles
from functools import partial
from pathlib import Path
import asyncio
from agent_comms.comms import Comms

from textual import on
from textual.app import ComposeResult
from textual import getters
from textual.binding import Binding
from textual.command import Hit, Hits, Provider, DiscoveryHit
from textual.content import Content
from textual.events import ScreenResume
from toad.screens.session_view import SessionView
from textual.reactive import var, reactive
from textual.widgets import (
    DirectoryTree,
    OptionList,
    Tree,
)
from textual import containers
from textual.widget import Widget


from toad.app import ToadApp
from toad import messages
from toad.agent_schema import Agent
from toad.acp import messages as acp_messages

from toad.widgets.plan import Plan
from toad.widgets.throbber import Throbber
from toad.widgets.conversation import Conversation, ThreadLoading
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.project_panel import ProjectPanel, ProjectSearchButton
from toad.widgets.recovery_view import RecoveryView
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar
from toad.widgets.comms_chat import resolve_session_thread, session_thread_name
from toad.widgets.comms_fork_dialog import ForkDialog
from toad.widgets.comms_sidebar import CoordinationStatus, CommsSidebar, SelectTarget
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.side_bar import SideBar, ThreadSidebar, SideBarCollapsible, TabHistoryControls
from toad.navigation_target import FeedTarget, DirectTarget, NavigationContext, NavigationOwner
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.footer import Footer
from toad.session_tracker import SidebarState


class ModeProvider(Provider):
    async def search(self, query: str) -> Hits:
        """Search for Python files."""
        matcher = self.matcher(query)

        screen = self.screen
        assert isinstance(screen, MainScreen)

        for mode in sorted(
            screen.conversation.modes.values(), key=lambda mode: mode.name
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
        screen = self.screen
        assert isinstance(screen, MainScreen)

        for mode in sorted(
            screen.conversation.modes.values(), key=lambda mode: mode.name
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
        screen = self.screen
        assert isinstance(screen, MainScreen)
        if score > 0:
            yield Hit(score, matcher.highlight("Pi MCP inventory"),
                      screen.action_mcp_inventory, help="Read-only package snapshot")

    async def discover(self) -> Hits:
        screen = self.screen
        assert isinstance(screen, MainScreen)
        yield DiscoveryHit("Pi MCP inventory", screen.action_mcp_inventory,
                           help="Read-only package snapshot")


class MainScreen(SessionView, NavigationOwner, can_focus=False):
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
    side_bar = getters.query_one(ChannelsSidebar)
    project_directory_tree = getters.query_one("#project_directory_tree")

    column = reactive(False)
    column_width = reactive(100)
    scrollbar = reactive("")
    project_path: var[Path] = var(Path("./").expanduser().absolute())

    app = getters.app(ToadApp)

    def __init__(
        self,
        project_path: Path,
        agent: Agent | None = None,
        agent_session_id: str | None = None,
        agent_session_title: str | None = None,
        session_pk: int | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()
        self.set_reactive(MainScreen.project_path, project_path)
        self._agent = agent
        self._agent_session_id = agent_session_id
        self._agent_session_title = agent_session_title
        self._coordination_root: str | None = None
        self._identity_wire: Comms | None = None
        self._comms_thread = (
            ""
            if agent is not None and agent["identity"] == "agent-comms.openhcs.dev"
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

    def watch_title(self, title: str) -> None:
        self.app.update_terminal_title()

    def get_loading_widget(self) -> Widget:
        return self.app.settings.ui.throbber.widget(self)

    def _on_screen_resume(self, event: ScreenResume) -> None:
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

        self._project_panel = ProjectPanel(self.project_path)
        with containers.Horizontal(id="tab-navigation-header"):
            yield TabHistoryControls()
            yield SessionsTabs()
        with containers.Center():
            yield ChannelsSlot()
            yield ThreadSidebar(
                SideBar.Panel("Thread", CoordinationStatus(self._comms_thread), id="coordination-panel"),
                SideBar.Panel("Comms", ThreadCommsSidebar(
                    self._comms_thread, wire_root=self._coordination_root, live=True),
                    id="thread-comms-panel", header_control=RelationshipSort()),
                SideBar.Panel("Plan", Plan([]), collapsed=True, id="plan-panel"),
                SideBar.Panel("Project", self._project_panel, flex=True, collapsed=True),
                SideBar.Panel("Recovery", RecoveryView(self._comms_thread,
                                                       wire_root=self._coordination_root), collapsed=True,
                              id="recovery-panel"),
                right=True, hide=True, navigation=self._thread_sidebar_state,
                defer_mount=not self._content_loaded,
            )
            with containers.Vertical(id="session-content"):
                if self._content_loaded:
                    yield self._make_conversation()
                else:
                    yield ThreadLoading(id="session-opening")
        yield Footer(compact=True)

    def _make_conversation(self) -> Conversation:
        with self._context():
            return Conversation(
                self.project_path, self._agent, self._agent_session_id,
                self._session_pk, self._agent_session_title,
                initial_prompt=self._initial_prompt,
            ).data_bind(project_path=MainScreen.project_path, column=MainScreen.column)

    def _start_content_hydration(self) -> None:
        if not self._content_loaded and not self._content_loading and self.is_attached:
            self._content_loading = True
            self.run_worker(self._load_content(), group="session-content")

    async def _load_content(self) -> None:
        try:
            for sidebar in self.query(SideBar):
                await sidebar.wait_content_ready()
            if not self.is_attached or self._closing:
                return
            content = self.query_one("#session-content", containers.Vertical)
            conversation = self._make_conversation()
            conversation.display = False
            # Mount asynchronously behind the loading row. No app-wide paint
            # mask: other tabs, cancellation and input remain available.
            await content.mount(conversation)
            if not self.is_attached or self._closing:
                return
            self._content_loaded = True
            self.watch_column(self.column)
            self.watch_scrollbar("", self.scrollbar)
            conversation.display = True
            await content.query("#session-opening").remove()
            if self.is_current and self.focused is None:
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

    def on_unmount(self) -> None:
        self._content_ready.set()

    def run_prompt(self, prompt: str) -> None:
        self.conversation

    def on_comms_session_named(self, thread_name: str) -> None:
        """Tell the sidebar which thread is this screen's session."""
        previous = self._comms_thread
        self._comms_thread = thread_name
        try:
            sidebar = self.query_one(CommsSidebar)
            sidebar.session_thread = thread_name
            sidebar._refresh()
        except Exception:
            pass
        if self.id is not None:
            self.app.sync_coordination_identity(self.id, previous, thread_name)
            details = self.app.session_tracker.get_session(self.id)
            if (
                details is not None
                and details.title in {"New Session", previous}
                and self._agent_session_title in {None, "New Session", previous}
            ):
                self._agent_session_title = thread_name
                self.app.session_tracker.update_session(self.id, title=thread_name)
        try:
            self.query_one(CoordinationStatus).set_thread(thread_name)
        except Exception:
            pass
        if recovery := self.query_one_optional(RecoveryView):
            recovery.set_identity(thread_name, self._coordination_root)
        if comms_tree := self.query_one_optional(ThreadCommsSidebar):
            comms_tree.set_identity(thread_name, self._coordination_root)
        if self.id is not None:
            self.app.sync_recovery_root(self.id, self._coordination_root)

    @on(acp_messages.CommsUpdated)
    async def on_comms_updated(self, event: acp_messages.CommsUpdated) -> None:
        await ScreenCommsConsumer(self).dispatch(event.update)

    @handles(CoordinationChangedUpdate)
    async def on_coordination_update(
        self, event: CoordinationChangedUpdate
    ) -> None:
        self._coordination_root = event.wire_root
        self.conversation.queue_supported = True
        if event.worktree is not None:
            project = Path(event.worktree)
            if project != self.project_path:
                self.project_path = project
                if self._project_panel is not None:
                    self._project_panel.path = project
                await self.conversation.sync_project_path(project)
                if self.id is not None:
                    self.app.sync_coordination_project(self.id, project)
        self.on_comms_session_named(event.thread.name)
        self.conversation.set_prompt_history_scope(f"thread:{event.thread.name}")

    _last_dm_target: str | None = None

    @property
    def _session_thread(self) -> str:
        return self._resolve_comms_thread()

    def _resolve_comms_thread(self) -> str:
        resolved: str | None
        try:
            from agent_comms.comms import wire

            from toad.comms_root import current_root, root_is_current

            if self._coordination_root is not None and not root_is_current(self._coordination_root):
                raise ValueError("Comms route changed; this session retains its former wire")
            root_path = (Path(self._coordination_root).expanduser()
                         if self._coordination_root is not None else current_root())
            if self._identity_wire is None or self._identity_wire.root != root_path:
                shared = self.app.coordination_wire
                self._identity_wire = shared if shared.root == root_path else wire(root_path)
            if self._coordination_root is not None:
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
                for name in sorted(sidebar._comms_registry_names())
                if name != self._session_thread
            ]
            target = peers[0] if peers else ""
        if target and self.id is not None:
            await self.open_sidebar_target(DirectTarget(target))

    @on(SelectTarget)
    async def on_comms_select_target(self, event: SelectTarget) -> None:
        """Open channels and DMs through Toad's native session modes."""
        await self.open_sidebar_target(event.target)

    @on(CommsSidebar.ThreadAction)
    async def on_comms_thread_action(self, event: CommsSidebar.ThreadAction) -> None:
        if event.action != "comms_fork":
            return
        parent = event.name

        def do_fork(spec: tuple[str, str] | None) -> None:
            if not spec:
                return
            from agent_comms import invoke_context_tool
            from agent_comms.comms import wire as _wire

            from toad.comms_root import implicit_root, root_is_current, run_selected_write

            try:
                if self._coordination_root is not None and not root_is_current(self._coordination_root):
                    raise ValueError("Comms route changed; reopen the thread before forking")
                comms = _wire()
                run_selected_write(
                    comms.root, invoke_context_tool, comms, event.action,
                    subject=parent, arguments={"name": spec[0], "task": spec[1]},
                    implicit=implicit_root(),
                )
                self.notify(f"forked {spec[0]} from {parent}", title="Comms")
            except Exception as error:
                self.notify(str(error), title="Comms fork failed", severity="error")

        self.app.push_screen(ForkDialog(parent), do_fork)

    def action_session_previous(self) -> None:
        if self.screen.id is not None:
            self.post_message(messages.SessionNavigate(self.screen.id, -1))

    def action_session_next(self) -> None:
        if self.screen.id is not None:
            self.post_message(messages.SessionNavigate(self.screen.id, +1))

    @on(messages.ProjectDirectoryUpdated)
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
        self.conversation.prompt.open_path_search()

    async def open_file_preview(self, path: Path) -> None:
        await self.app.open_file_preview(path)

    @on(acp_messages.Plan)
    async def on_acp_plan(self, message: acp_messages.Plan):
        message.stop()
        entries = [
            Plan.Entry(
                Content(entry["content"]),
                entry.get("priority", "medium"),
                entry.get("status", "pending"),
            )
            for entry in message.entries
        ]
        self.query_one("SideBar Plan", Plan).entries = entries
        if entries:
            self.query_one("#plan-panel", SideBarCollapsible).collapsed = False

    @on(messages.SessionUpdate)
    async def on_session_update(self, event: messages.SessionUpdate) -> None:
        # TODO: May not be required
        if event.name is not None:
            self._agent_session_title = event.name
        if self.id is not None:
            self.app.session_tracker.update_session(
                self.id,
                title=event.name,
                subtitle=event.subtitle,
                path=event.path,
                state=event.state,
                summary=event.summary,
            )

    @on(messages.SessionClose)
    async def on_session_close(self, event: messages.SessionClose) -> None:
        if self.id is None:
            return
        await self.app.close_session_mode(self.id)

    def on_mount(self) -> None:
        # Route discovery already resolved new wire-thread identities off-loop.
        if sidebar := self.query_one_optional(CommsSidebar):
            sidebar.session_thread = (
                self._comms_thread if self._coordination_root is not None
                else self._resolve_comms_thread()
            )
        if self._content_loaded:
            self._content_ready.set()
        else:
            self.call_after_first_frame(self, self._start_content_hydration)
        self.app.sidebar_layout_changed.subscribe(
            self, lambda _event: self._align_tabs_with_sidebar(False)
        )
        # Keep the screen-wide navigation row independent of sidebar geometry,
        # including when restoring a previously mounted owner tab.
        for tree in self.query("#project_directory_tree").results(DirectoryTree):
            tree.data_bind(path=MainScreen.project_path)
        for tree in self.query(DirectoryTree):
            tree.guide_depth = 3

    def _align_tabs_with_sidebar(self, _collapsed: bool) -> None:
        self.align_tabs_to_sidebars()

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
        await self.app.switch_mode("store")

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
