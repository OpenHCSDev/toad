from functools import partial
from pathlib import Path
import random
from agent_comms import Comms

from textual import on
from textual.app import ComposeResult
from textual import getters
from textual.binding import Binding
from textual.command import Hit, Hits, Provider, DiscoveryHit
from textual.content import Content
from textual.events import Resize, ScreenResume
from textual.screen import Screen
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
from toad.widgets.conversation import Conversation
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.project_panel import ProjectPanel, ProjectSearchButton
from toad.widgets.recovery_view import RecoveryView
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar
from toad.widgets.comms_chat import resolve_session_thread, session_thread_name
from toad.widgets.comms_fork_dialog import ForkDialog
from toad.widgets.comms_sidebar import CoordinationStatus, CommsSidebar, SelectTarget
from toad.widgets.side_bar import SideBar, SideBarCollapsible, TabHistoryControls
from toad.widgets.session_sort import ChannelListSort
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


class MainScreen(SessionView, can_focus=False):
    AUTO_FOCUS = "Conversation Prompt TextArea"

    CSS_PATH = "main.tcss"

    COMMANDS = {ModeProvider}

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
    side_bar = getters.query_one(SideBar)
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

    def watch_title(self, title: str) -> None:
        self.app.update_terminal_title()

    def get_loading_widget(self) -> Widget:
        throbber = self.app.settings.get("ui.throbber", str)
        if throbber == "quotes":
            from toad.app import QUOTES
            from toad.widgets.future_text import FutureText

            quotes = QUOTES.copy()
            random.shuffle(quotes)
            return FutureText([Content(quote) for quote in quotes])
        return super().get_loading_widget()

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
        self._align_tabs_with_sidebar(
            self.query_one("#channels-sidebar", SideBar).collapsed
        )
        self.conversation
        if watcher := self.conversation._directory_watcher:
            self.call_after_refresh(watcher.notify_if_visible)
        if self._project_panel is not None:
            self.call_after_refresh(self._project_panel.refresh_if_visible)

    def compose(self) -> ComposeResult:
        self._project_panel = ProjectPanel(self.project_path)
        with containers.Horizontal(id="tab-navigation-header"):
            yield TabHistoryControls()
            yield SessionsTabs()
        with containers.Center():
            yield SideBar(
                SideBar.Panel(
                    "Channels",
                    CommsSidebar(session_thread=self._comms_thread),
                    flex=True,
                    header_control=ChannelListSort(),
                ),
                id="channels-sidebar",
            )
            yield SideBar(
                SideBar.Panel("Thread", CoordinationStatus(self._comms_thread), id="coordination-panel"),
                SideBar.Panel("Comms", ThreadCommsSidebar(
                    self._comms_thread, wire_root=self._coordination_root, live=True),
                    id="thread-comms-panel", header_control=RelationshipSort()),
                SideBar.Panel("Plan", Plan([]), collapsed=True, id="plan-panel"),
                SideBar.Panel("Project", self._project_panel, flex=True, collapsed=True),
                SideBar.Panel("Recovery", RecoveryView(self._comms_thread,
                                                       wire_root=self._coordination_root), collapsed=True,
                              id="recovery-panel"),
                id="thread-sidebar", right=True, hide=True, navigation=self._thread_sidebar_state,
            )
            with containers.Vertical(id="session-content"):
                yield Conversation(
                    self.project_path,
                    self._agent,
                    self._agent_session_id,
                    self._session_pk,
                    self._agent_session_title,
                    initial_prompt=self._initial_prompt,
                ).data_bind(
                    project_path=MainScreen.project_path,
                    column=MainScreen.column,
                )
        yield Footer(compact=True)

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
                previous != thread_name
                and details is not None
                and details.title == previous
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

    @on(acp_messages.CoordinationUpdate)
    async def on_coordination_update(
        self, event: acp_messages.CoordinationUpdate
    ) -> None:
        self._coordination_root = event.wire_root
        self.conversation.queue_supported = event.prompt_queue
        if event.worktree is not None:
            project = Path(event.worktree)
            if project != self.project_path:
                self.project_path = project
                if self._project_panel is not None:
                    self._project_panel.path = project
                await self.conversation.sync_project_path(project)
                if self.id is not None:
                    self.app.sync_coordination_project(self.id, project)
        self.on_comms_session_named(event.thread)
        self.conversation.set_prompt_history_scope(f"thread:{event.thread}")

    _last_dm_target: str | None = None

    @property
    def _session_thread(self) -> str:
        return self._resolve_comms_thread()

    def _resolve_comms_thread(self) -> str:
        resolved: str | None
        try:
            import os

            from agent_comms.operations import wire

            root = self._coordination_root or os.environ.get(
                "AGENT_COMMS_ROOT", "~/.agent-comms"
            )
            root_path = Path(root).expanduser()
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

    async def _open_comms(self, target: str, kind: str) -> None:
        if self.id is None:
            return
        await self.app.open_comms_session(
            owner_mode=self.id,
            project_path=self.project_path,
            me=self._session_thread,
            target=target,
            kind=kind,
        )

    async def action_toggle_irc(self) -> None:
        """Open the IRC feed as a native Toad session."""
        from toad.constants import ALL_COMMS_TARGET

        await self._open_comms(ALL_COMMS_TARGET, "irc")

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
        if target:
            await self._open_comms(target, "dm")

    @on(SelectTarget)
    async def on_comms_select_target(self, event: SelectTarget) -> None:
        """Open channels and DMs through Toad's native session modes."""
        if event.kind == "session":
            return
        if event.kind == "dm":
            self._last_dm_target = event.target
        await self._open_comms(event.target, event.kind)

    @on(CommsSidebar.ThreadAction)
    async def on_comms_thread_action(self, event: CommsSidebar.ThreadAction) -> None:
        if event.action != "comms_fork":
            return
        parent = event.name

        def do_fork(spec: tuple[str, str] | None) -> None:
            if not spec:
                return
            import os as _os

            from agent_comms import invoke_context_tool
            from agent_comms.operations import wire as _wire

            root = _os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")
            try:
                invoke_context_tool(
                    _wire(root),
                    event.action,
                    subject=parent,
                    arguments={"name": spec[0], "task": spec[1]},
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
        self.query_one(CommsSidebar).session_thread = self._resolve_comms_thread()
        # The tab header sits above (not inside) the resizable left sidebar.
        # Use its current computed width so the first frame and every toggle
        # align the tabs with the conversation without a deferred paint.
        self.watch(
            self.query_one("#channels-sidebar", SideBar),
            "collapsed",
            self._align_tabs_with_sidebar,
        )
        for tree in self.query("#project_directory_tree").results(DirectoryTree):
            tree.data_bind(path=MainScreen.project_path)
        for tree in self.query(DirectoryTree):
            tree.guide_depth = 3

    def on_resize(self, _event: Resize) -> None:
        if sidebar := self.query_one_optional("#channels-sidebar", SideBar):
            self._align_tabs_with_sidebar(sidebar.collapsed)

    def _align_tabs_with_sidebar(self, _collapsed: bool) -> None:
        sidebar = self.query_one("#channels-sidebar", SideBar)
        header = self.query_one("#tab-navigation-header", containers.Horizontal)
        width = sidebar.styles.width.resolve(self.size, self.app.size)
        # On narrow terminals the CSS max-width (45%) clips the expanded
        # sidebar below its nominal 40 cells; use that same cap on the header.
        if maximum := sidebar.styles.max_width:
            width = min(width, maximum.resolve(self.size, self.app.size))
        left = int(width)
        if header.styles.padding.left != left:
            header.styles.padding = (0, 0, 0, left)

    @on(OptionList.OptionHighlighted)
    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option.id is not None:
            self.conversation.prompt.suggest(event.option.id)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "show_sidebar" and self.side_bar.has_focus_within:
            return False
        return True

    def action_show_sidebar(self) -> None:
        self.side_bar.reveal()
        self.side_bar.query_one("SideBarCollapsible CollapsibleTitle").focus()

    def action_focus_prompt(self) -> None:
        self.conversation.focus_prompt()

    async def action_go_home(self) -> None:
        await self.app.switch_mode("store")

    @on(SideBar.Dismiss)
    def on_side_bar_dismiss(self, message: SideBar.Dismiss):
        message.stop()
        self.conversation.focus_prompt(scroll_end=False)

    def watch_column(self, column: bool) -> None:
        self.conversation.styles.max_width = (
            max(10, self.column_width) if column else None
        )

    def watch_column_width(self, column_width: int) -> None:
        self.conversation.styles.max_width = (
            max(10, column_width) if self.column else None
        )

    def watch_scrollbar(self, old_scrollbar: str, scrollbar: str) -> None:
        if old_scrollbar:
            self.conversation.remove_class(f"-scrollbar-{old_scrollbar}")
        if scrollbar:
            self.conversation.add_class(f"-scrollbar-{scrollbar}")
