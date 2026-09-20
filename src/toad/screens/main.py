from functools import partial
from pathlib import Path
import random

from textual import on
from textual.app import ComposeResult
from textual import getters
from textual.binding import Binding
from textual.command import Hit, Hits, Provider, DiscoveryHit
from textual.content import Content
from textual.events import ScreenResume
from textual.screen import Screen
from textual.reactive import var, reactive
from textual.widgets import Footer, OptionList, DirectoryTree, Tree
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
from toad.widgets.comms_chat import resolve_session_thread, session_thread_name
from toad.widgets.comms_fork_dialog import ForkDialog
from toad.widgets.comms_sidebar import CoordinationStatus, CommsSidebar, SelectTarget
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.session_tabs import SessionsTabs


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


class MainScreen(Screen, can_focus=False):
    AUTO_FOCUS = "Conversation Prompt TextArea"

    CSS_PATH = "main.tcss"

    COMMANDS = {ModeProvider}

    SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")
    BINDINGS = [
        Binding("ctrl+g", "toggle_irc", "IRC view"),
        Binding("ctrl+j", "toggle_dm", "DM view"),
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
        self._comms_thread = (
            ""
            if agent is not None and agent["identity"] == "agent-comms.openhcs.dev"
            else session_thread_name(project_path)
        )
        self._session_pk = session_pk
        self._initial_prompt = initial_prompt

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
            sidebar.session_thread = self._resolve_comms_thread()
            self.call_after_refresh(sidebar.sync_sessions)
        except Exception:
            pass
        self.conversation

    def compose(self) -> ComposeResult:
        with containers.Center():
            yield SideBar(
                SideBar.Panel(
                    "Sessions",
                    CommsSidebar(session_thread=self._comms_thread),
                ),
                SideBar.Panel(
                    "Coordination",
                    CoordinationStatus(self._comms_thread),
                    id="coordination-panel",
                ),
                SideBar.Panel("Plan", Plan([]), collapsed=True, id="plan-panel"),
                SideBar.Panel(
                    "Project",
                    ProjectDirectoryTree(
                        self.project_path,
                        id="project_directory_tree",
                    ),
                    flex=True,
                ),
            )
            with containers.Vertical(id="session-content"):
                yield SessionsTabs()
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
        if self.id is not None and previous and previous != thread_name:
            self.app.sync_coordination_identity(self.id, previous, thread_name)
        try:
            self.query_one(CoordinationStatus).set_thread(thread_name)
        except Exception:
            pass

    @on(acp_messages.CoordinationUpdate)
    def on_coordination_update(self, event: acp_messages.CoordinationUpdate) -> None:
        self._coordination_root = event.wire_root
        self.on_comms_session_named(event.thread)

    _last_dm_target: str | None = None

    @property
    def _session_thread(self) -> str:
        return self._resolve_comms_thread()

    def _resolve_comms_thread(self) -> str:
        try:
            import os

            from agent_comms.operations import wire

            root = self._coordination_root or os.environ.get(
                "AGENT_COMMS_ROOT", "~/.agent-comms"
            )
            resolved = resolve_session_thread(
                wire(root), self.project_path, self._comms_thread
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
        await self._open_comms("#all", "irc")

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
        if event.action != "fork":
            return
        parent = event.name

        def do_fork(spec: tuple[str, str] | None) -> None:
            if not spec:
                return
            import os as _os

            from agent_comms.operations import wire as _wire

            root = _os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")
            from agent_comms.operations import ForkSpec

            try:
                _wire(root).fork(ForkSpec(name=spec[0], parent=parent, task=spec[1]))
                self.notify(f"forked {spec[0]} from {parent}", title="Comms")
            except Exception as error:
                self.notify(str(error), title="Comms fork failed", severity="error")

        self.app.push_screen(ForkDialog(parent), do_fork)

    def update_node_styles(self, animate: bool = True) -> None:
        self.conversation.update_node_styles(animate=animate)
        self.query_one(Footer).update_node_styles(animate=animate)
        self.query_one(SideBar).update_node_styles(animate=animate)

    def action_session_previous(self) -> None:
        if self.screen.id is not None:
            self.post_message(messages.SessionNavigate(self.screen.id, -1))

    def action_session_next(self) -> None:
        if self.screen.id is not None:
            self.post_message(messages.SessionNavigate(self.screen.id, +1))

    @on(messages.ProjectDirectoryUpdated)
    async def on_project_directory_update(self) -> None:
        await self.query_one(ProjectDirectoryTree).reload()

    @on(DirectoryTree.FileSelected, "ProjectDirectoryTree")
    def on_project_directory_tree_selected(self, event: Tree.NodeSelected):
        if (data := event.node.data) is not None:
            self.conversation.insert_path_into_prompt(data.path)

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
            if self._coordination_root:
                try:
                    from agent_comms.operations import wire

                    thread = wire(self._coordination_root).registry.require(event.name)
                    if Path(thread.worktree).resolve() == self.project_path.resolve():
                        self.on_comms_session_named(thread.name)
                except Exception:
                    pass
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
        import gc

        gc.freeze()
        self.query_one(CommsSidebar).session_thread = self._resolve_comms_thread()
        for tree in self.query("#project_directory_tree").results(DirectoryTree):
            tree.data_bind(path=MainScreen.project_path)
        for tree in self.query(DirectoryTree):
            tree.guide_depth = 3

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
        self.side_bar.query_one("Collapsible CollapsibleTitle").focus()

    def action_focus_prompt(self) -> None:
        self.conversation.focus_prompt()

    async def action_go_home(self) -> None:
        await self.app.switch_mode("store")

    @on(SideBar.Dismiss)
    def on_side_bar_dismiss(self, message: SideBar.Dismiss):
        message.stop()
        self.conversation.focus_prompt()

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
