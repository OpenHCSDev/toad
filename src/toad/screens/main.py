import asyncio
from abc import abstractmethod
from collections.abc import Iterable
from functools import partial
from pathlib import Path

from acp.exceptions import RequestError
from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.coordination_errors import DMScopeChanged
from agent_comms.declared_family import DeclaredFamily
from agent_comms.mro_dispatch import handles
from agent_comms.route_selection import RouteSelection
from textual import containers, getters, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider, SimpleCommand
from textual.reactive import var
from textual.widget import Widget
from textual.widgets import (
    DirectoryTree,
    OptionList,
    Static,
    Tree,
)

from toad.acp.agent_session import SessionDisposition
from toad.app import ToadApp
from toad.core import events as core_events
from toad.core import input_events, session_requests
from toad.core.events import SessionChangedEvent
from toad.core.input_events import SelectTarget
from toad.format_path import format_path
from toad.navigation_context import NavigationContext
from toad.navigation_target import (
    DirectTarget,
    FeedTarget,
    NavigationTarget,
    ThreadTarget,
)
from toad.screens.commander import CommanderPage
from toad.screens.mcp_inventory import MCPInventoryScreen
from toad.screens.session_view import SessionView
from toad.session_presentation import OperationalSessionPresentation
from toad.session_scope import AgentBinding, NoAgent, ViewSessionOrigin
from toad.session_tracker import SessionDetails, SidebarState
from toad.tab_identity.history_origin import SessionHistoryOrigin
from toad.thread_identity import NoThreadIdentity, ThreadIdentity
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.conversation import Conversation
from toad.widgets.message_notifications import NothingToRead, PaintedRead, ReadWork
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.project_panel import ProjectPanel, ProjectSearchButton
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.side_bar import SideBar
from toad.widgets.splash_text import ThreadLoading


class SessionCommands(Provider):
    @property
    def session(self) -> MainScreen:
        screen = self.screen.app.selected_session
        assert isinstance(screen, MainScreen)
        return screen

    @abstractmethod
    def commands(self, session: MainScreen) -> Iterable[SimpleCommand]: ...

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, callback, help_text in self.commands(self.session):
            if (score := matcher.match(name)) > 0:
                yield Hit(score, matcher.highlight(name), callback, help=help_text)

    async def discover(self) -> Hits:
        for name, callback, help_text in self.commands(self.session):
            yield DiscoveryHit(name, callback, help=help_text)


class ModeProvider(SessionCommands):
    def commands(self, session: MainScreen) -> Iterable[SimpleCommand]:
        for mode in sorted(
            session.conversation.agent_binding.available_modes,
            key=lambda mode: mode.name,
        ):
            yield SimpleCommand(
                mode.name,
                partial(session.conversation.set_mode, mode.value),
                mode.description,
            )


class MCPInventoryProvider(SessionCommands):
    def commands(self, session: MainScreen) -> Iterable[SimpleCommand]:
        yield SimpleCommand(
            "Pi MCP inventory",
            session.action_mcp_inventory,
            "Read-only package snapshot",
        )


class ScreenContent(DeclaredFamily, affix="Content"):
    """Content state owns its label, preparation slot and completion."""

    @abstractmethod
    def line(self) -> str:
        """The opening line this content state shows; empty hides it."""

    def render(self, screen: "MainScreen") -> Static:
        """Describe content preparation; connection state belongs to its status row."""
        line = self.line()
        return self.label(screen, line, visible=bool(line))

    @abstractmethod
    async def wait(self, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def prepare(self, screen: "MainScreen") -> None: ...

    def finish(self, screen: "MainScreen", content: "ScreenContent") -> None:
        screen.content = content
        content.render(screen)

    def close(self, screen: "MainScreen") -> None:
        """Terminal content has no unfinished waiters to release."""

    async def attached(self, screen: "MainScreen") -> None:
        """Repaint the current content state when its session becomes ready."""
        self.render(screen)

    def label(self, screen: "MainScreen", text: str, *, visible: bool) -> Static:
        label = screen.query_one_optional("#session-opening", Static)
        if label is None:
            label = Static(id="session-opening", markup=False)
        label.update(text)
        label.display = visible
        return label


class OpeningContent(ScreenContent):
    def __init__(self) -> None:
        self.completion = asyncio.get_running_loop().create_future()

    def line(self) -> str:
        return ThreadLoading.LABEL

    async def wait(self, screen: "MainScreen") -> None:
        await asyncio.shield(self.completion)
        await screen.content.wait(screen)

    async def prepare(self, screen: "MainScreen") -> None:
        await screen._prepare_content()

    def finish(self, screen: "MainScreen", content: ScreenContent) -> None:
        super().finish(screen, content)
        self.completion.set_result(None)

    def close(self, screen: "MainScreen") -> None:
        self.finish(screen, ReadyContent())


class NavigatedOpeningContent(OpeningContent):
    async def prepare(self, screen: "MainScreen") -> None:
        """Navigation runs _prepare_content after mounting; selecting the shell does no I/O."""


class ReadyContent(ScreenContent):
    async def prepare(self, screen: "MainScreen") -> None:
        await screen._prepare_content()

    def line(self) -> str:
        return ""

    async def wait(self, screen: "MainScreen") -> None:
        """The content has already been accepted."""


class FailedContent(ScreenContent):
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def line(self) -> str:
        return f"Thread unavailable: {self.error}"

    async def wait(self, screen: "MainScreen") -> None:
        raise self.error

    async def prepare(self, screen: "MainScreen") -> None:
        agent = screen.presentation.operational_binding
        if agent.ready:
            await self.attached(screen)
        else:
            self.render(screen)

    async def attached(self, screen: "MainScreen") -> None:
        self.finish(screen, ReadyContent())
        if screen.is_current:
            await screen.prepare_presentation()


class MainScreen(ViewSessionOrigin, SessionView, can_focus=False):
    footer_compact = True

    AUTO_FOCUS = "Conversation Prompt TextArea"

    CSS_PATH = "main.tcss"

    COMMANDS = {ModeProvider, MCPInventoryProvider}

    SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")
    BINDINGS = [
        Binding("ctrl+g", "toggle_irc", "IRC view"),
        Binding("ctrl+h", "go_home", "Home", show=False),
        Binding("f2", "commander_page", "Commander"),
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
    conversation = getters.query_one(Conversation)
    thread_sidebar = getters.query_one(SessionThreadSidebar)

    @property
    def side_bar(self):
        return self.screen.query_one(ChannelsSidebar)

    project_path: var[Path] = var(Path("./").expanduser().absolute())

    app = getters.app(ToadApp)

    def __init__(
        self,
        project_path: Path,
        binding: AgentBinding = NoAgent(),
        session_pk: int | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()
        self.set_reactive(MainScreen.project_path, project_path)
        self._agent_binding = binding
        self._identity = binding.initial_identity(NoThreadIdentity())
        self._session_pk = session_pk
        self._initial_prompt = initial_prompt
        self._thread_sidebar_state = SidebarState()
        self._project_panel: ProjectPanel | None = None
        self.content: ScreenContent = OpeningContent()
        self.presentation = OperationalSessionPresentation()

    def read_visible(self) -> PaintedRead:
        """Capture this session's painted cursor before its guarded backend write."""
        conversation = self.query_one_optional(Conversation)
        if conversation is None:
            return NothingToRead()
        through = conversation.visible_read_cursor
        if through is None:
            return NothingToRead()
        app = self.app
        access = app.coordination_access
        identity = self.thread_identity
        project = self.project_path
        source_root = identity.wire_root()
        worktree = str(app.project_dir)

        def acknowledge(cursor) -> None:
            selected = RouteSelection.capture(source_root)
            comms = access.require(selected).service

            def mark() -> None:
                resolved = identity.resolve_thread(comms.registry, project)
                comms.views.mark_thread_view_read(
                    resolved, worktree=worktree, through=cursor
                )

            access.write(selected, mark)

        async def mark():
            try:
                await conversation.transcript.mark_read(
                    through,
                    acknowledge,
                    lambda: app.selected_session is self,
                )
            except DMScopeChanged as error:
                app.show_error(error, "DM read not marked")

        return ReadWork(mark())

    @classmethod
    def from_thread(
        cls, project: Path, root: str, target, binding: AgentBinding = NoAgent()
    ) -> "MainScreen":
        screen = cls(project, binding.for_session(target.name))
        screen.bind_thread(target, root)
        return screen

    def bind_thread(self, owner, root: str) -> None:
        with self.changing_identity():
            self._identity = ThreadIdentity(owner, root)

    def identity_changed(self, previous) -> None:
        if self.id is not None:
            self.app.session_tracker.bind_identity(
                self.session_details.identity, previous.thread_name(), self.thread_identity.thread_name()
            )

    @classmethod
    def opening(cls, request, origin, app) -> "MainScreen":
        # The request has only a name; bind the wire after its metadata read.
        screen = cls(
            request.project,
            origin.source.agent_for_opening(app.agent_binding).for_session(request.target),
        )
        screen.content = NavigatedOpeningContent()
        return screen

    async def prepare_presentation(self) -> None:
        await self.content.prepare(self)

    async def _prepare_content(self) -> None:
        try:
            await self.presentation.prepare(self)
            await super().prepare_presentation()
            await self.thread_sidebar.prepare_presentation()
        except asyncio.CancelledError as error:
            self.opening_failed(error)
            raise
        except RequestError as error:
            self.opening_failed(error)
        else:
            self.content.finish(self, ReadyContent())

    def opening_failed(self, error: BaseException) -> None:
        self.content.finish(self, FailedContent(error))

    async def retire_presentation(self) -> None:
        # The departing scene is still committed here. Awaiting source/sidebar
        # retirement can publish a new layout which no longer contains it.
        await super().retire_presentation()
        await self.thread_sidebar.retire_presentation()
        await self.presentation.retire(self)

    def retained_native_presentations(self):
        resources = (
            [(self, self.presentation)] if self.presentation.widget is not None else []
        )
        sidebar = self.thread_sidebar
        if sidebar.panels_loaded:
            resources.append((self, sidebar))
        return tuple(resources)

    @property
    def session_disposition(self) -> SessionDisposition:
        return self.presentation.operational_binding.session_disposition

    session_details: SessionDetails

    def history_origin(self) -> SessionHistoryOrigin:
        return SessionHistoryOrigin(self.session_details.identity)
    """The registered entry supplies its existing details before mounting this view."""

    def make_conversation(self) -> Conversation:
        return self._agent_binding.make_conversation(
            partial(
                Conversation,
                self.project_path,
                session_pk=self._session_pk,
                session_title=self.session_details.initial_title,
                initial_prompt=self._initial_prompt,
                transcript=self.presentation.transcript,
            )
        )

    def watch_title(self, title: str) -> None:
        self.app.terminal_attention.update()

    def get_loading_widget(self) -> Widget:
        return self.app.settings.ui.throbber.widget(self)

    def activate_session(self) -> None:
        # The identity is updated by ACP's coordination notification and
        # cached on this screen. Resolving it through the wire here can
        # block the first frame of every navigation on store I/O.
        if self._project_panel is not None:
            self.call_after_refresh(self._project_panel.refresh_if_visible)

    def sidebars(self):
        return (self.thread_sidebar,)

    def compose(self) -> ComposeResult:
        with containers.Center().set_styles(layout=self.app.workspace_chrome):
            yield SessionThreadSidebar(self)
            with containers.Vertical(id="session-content"):
                yield self.content.render(self)
                yield self.presentation.compose_content(self)

    def update_title(self) -> None:
        """The screen's title names the session and the project it presents."""
        self.title = f"{self.display_name} {format_path(self.project_path)}"

    async def wait_content_ready(self) -> None:
        if self._closing or self._closed:
            return
        await self.content.wait(self)

    async def close_presentation(self) -> None:
        await self.thread_sidebar.evict()
        self.content.close(self)
        await self.presentation.close(self)

    @handles(core_events.CommsUpdated)
    async def on_comms_updated(self, event: core_events.CommsUpdated) -> None:
        await self.dispatch(event.update)

    @handles(core_events.ExternalTranscriptChanged, core_events.SessionSelected)
    def external_transcript_changed(self, event: core_events.ExternalTranscriptChanged | core_events.SessionSelected) -> None:
        if self.is_current:
            self.presentation.external_transcript_changed()

    def bind_project(self, project: Path) -> None:
        """The accepted source and later coordination updates use one project owner."""
        if project != self.project_path:
            self.project_path = project
            if self._project_panel is not None:
                self._project_panel.path = project
            if self.id is not None:
                self.app.session_navigation.sync_project(self.id, project)
            self.update_title()
            self.link_context_changed()

    @handles(CoordinationChangedUpdate)
    async def on_coordination_update(self, event: CoordinationChangedUpdate) -> None:
        async with self.presentation.transcript.changing_source(self):
            with self.changing_identity():
                previous_root = self.coordination_root
                self._identity = ThreadIdentity(event.thread, event.wire_root)
                if previous_root != self.coordination_root:
                    self.link_context_changed()
                if event.worktree is not None:
                    self.bind_project(Path(event.worktree))
                if self.id is not None:
                    self.app.session_navigation.sync_owner_root(
                        self.id, self.coordination_root
                    )
        await self.presentation.apply_coordination(self, event)

    @handles(core_events.AgentReady)
    async def on_session_attached(self, event: core_events.AgentReady) -> None:
        with self.changing_identity() as previous:
            self._identity = previous.with_session(event.session_id)
        await self.content.attached(self)

    _last_dm_target: str | None = None

    @property
    def navigation_target(self) -> NavigationTarget:
        return ThreadTarget(self.thread_identity.thread_name())

    @property
    def navigation_context(self) -> NavigationContext:
        assert self.id is not None
        return NavigationContext(
            self.app, self.id, self.project_path, self.thread_identity.thread_name()
        )

    def remember_direct_target(self, target: str) -> None:
        self._last_dm_target = target

    def action_mcp_inventory(self) -> None:
        """Open an inert package-owned snapshot; never locate a source checkout."""
        self.app.push_screen(
            MCPInventoryScreen(
                self.project_path,
            )
        )

    async def action_toggle_irc(self) -> None:
        """Open the IRC feed as a native Toad session."""
        if self.id is not None:
            await self.open_sidebar_target(FeedTarget())

    async def open_direct_messages(self) -> None:
        """Open the last-selected DM as a native Toad session."""
        target = self._last_dm_target
        if not target:
            self.notify(
                "Choose Direct messages from an agent's context menu",
                title="Direct messages",
            )
            return
        if target and self.id is not None:
            await self.open_sidebar_target(DirectTarget(target))

    @handles(SelectTarget)
    async def on_comms_select_target(self, event: SelectTarget) -> None:
        """Open channels and DMs through Toad's native session modes."""
        await self.open_sidebar_target(event.target)

    def action_session_previous(self) -> None:
        if self.id is not None:
            self.app.session_navigation.events.publish(
                session_requests.SessionNavigate(self.id, -1)
            )

    def action_session_next(self) -> None:
        if self.id is not None:
            self.app.session_navigation.events.publish(
                session_requests.SessionNavigate(self.id, +1)
            )

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
    async def on_acp_plan(self, event: core_events.Plan):
        self.thread_sidebar.update_plan(event.entries)

    @handles(SessionChangedEvent)
    def on_session_details_changed(self, event: SessionChangedEvent) -> None:
        if event.mode_name == self.id:
            self.update_title()

    @handles(core_events.ThreadRowsChanged)
    def on_session_tabs_changed(self, event: core_events.ThreadRowsChanged) -> None:
        self.update_title()

    @handles(core_events.SessionTitleChanged)
    def on_session_title_changed(self, event: core_events.SessionTitleChanged) -> None:
        """The user or the agent process named this session; the tab keeps it."""
        if self.id is not None:
            self.app.session_tracker.name_session(self.session_details.identity, event.name)

    @handles(core_events.SessionThreadTitle)
    def on_session_thread_title(self, event: core_events.SessionThreadTitle) -> None:
        """The thread presented a title; an authored name keeps the tab's label."""
        if (details := self.app.session_tracker.get_session(self.session_details.identity)) is not None:
            if details.update_thread_title(event.title):
                self.app.session_tracker.events.publish(SessionChangedEvent(self.id))

    @handles(core_events.SessionSubtitleChanged)
    def on_session_subtitle_changed(self, event: core_events.SessionSubtitleChanged) -> None:
        if self.id is not None:
            self.app.session_tracker.update_session(
                self.session_details.identity, subtitle=event.subtitle
            )

    @handles(core_events.SessionPathChanged)
    def on_session_path_changed(self, event: core_events.SessionPathChanged) -> None:
        if self.id is not None:
            self.app.session_tracker.update_session(self.session_details.identity, path=event.path)

    def on_mount(self) -> None:
        self.observe_core(self.app.events)
        self.observe_core(self.app.coordination_access.events)
        self.observe_core(self.app.session_tracker.events)
        # Keep the screen-wide navigation row independent of sidebar geometry,
        # including when restoring a previously mounted owner tab.
        self.update_title()

    @on(OptionList.OptionHighlighted)
    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option.id is not None:
            self.conversation.prompt.suggest(event.option.id)

    def action_focus_prompt(self) -> None:
        if conversation := self.query_one_optional(Conversation):
            conversation.focus_prompt()

    def focus_sidebar_return(self) -> None:
        if conversation := self.query_one_optional(Conversation):
            target = conversation.prompt.prompt_text_area
            if target.focusable:
                self.screen.set_focus(target, scroll_visible=False)

    def action_commander_page(self) -> None:
        """Every unit's state, orders and PRs, as the commander heartbeat published them."""
        self.app.push_screen(CommanderPage())

    async def action_go_home(self) -> None:
        await self.app.select_session("store")

    @on(SideBar.Dismiss)
    def on_side_bar_dismiss(self, message: SideBar.Dismiss):
        message.stop()
        if conversation := self.query_one_optional(Conversation):
            conversation.focus_prompt(scroll_end=False)
