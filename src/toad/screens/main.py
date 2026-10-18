from toad.core import input_events
from toad.core_event_carrier import CoreEventMessage
from toad.core import session_requests, events as core_events
from toad.core.events import SessionChangedEvent
from toad.format_path import format_path
import asyncio
from abc import abstractmethod
from functools import partial
from pathlib import Path
from typing import cast

from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.declared_family import DeclaredFamily
from agent_comms.mro_dispatch import MroDispatch, handles
from textual import containers, getters, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.content import Content
from textual.events import ScreenResume
from textual.reactive import var
from textual.widget import Widget
from textual.widgets import (
    DirectoryTree,
    OptionList,
    Static,
    Tree,
)

from toad import messages

from toad.acp.agent_session import SessionDisposition
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.navigation_target import NavigationContext, NavigationOwner
from toad.screens.session_view import SessionOrigin, SessionView
from toad.screens.mcp_inventory import MCPInventoryScreen
from toad.session_presentation import OperationalSessionPresentation
from toad.session_tracker import SidebarState
from toad.core.input_events import SelectTarget
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.conversation import Conversation, ThreadLoading
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.project_panel import ProjectPanel, ProjectSearchButton
from toad.widgets.side_bar import SideBar, SideBarCollapsible
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


class ScreenContent(DeclaredFamily, affix="Content"):
    """Content state owns its label, preparation slot and completion."""

    @abstractmethod
    def line(self) -> str:
        """The opening line this content state shows; empty hides it."""

    def render(self, screen: "MainScreen") -> Static:
        """The opening line: the session's disposition decides whether a failure replaces it."""
        line = screen.session_disposition.present(self.line(), lambda status: status.notice)
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
        """Refresh connection feedback from the session that just became ready."""
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
        agent = screen.presentation.operational_agent
        if agent is not None and agent.ready:
            await self.attached(screen)
        else:
            self.render(screen)

    async def attached(self, screen: "MainScreen") -> None:
        self.finish(screen, ReadyContent())
        if screen.is_current:
            await screen.prepare_presentation()


class MainScreen(SessionOrigin, SessionView, NavigationOwner, can_focus=False):
    footer_compact = True

    AUTO_FOCUS = "Conversation Prompt TextArea"

    CSS_PATH = "main.tcss"

    COMMANDS = {ModeProvider, MCPInventoryProvider}

    SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")
    BINDINGS = [
        Binding("ctrl+g", "toggle_irc", "IRC view"),
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
    conversation = getters.query_one(Conversation)
    thread_sidebar = getters.query_one(SessionThreadSidebar)
    @property
    def side_bar(self):
        return self.screen.query_one(ChannelsSidebar)
    project_directory_tree = getters.query_one("#project_directory_tree")

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
        from toad.thread_identity import SessionIdentity
        self._identity = SessionIdentity.for_thread(agent_session_id or "", None)
        self._session_pk = session_pk
        self._initial_prompt = initial_prompt
        self._thread_sidebar_state = SidebarState()
        self._project_panel: ProjectPanel | None = None
        self.content: ScreenContent = OpeningContent()
        self.presentation = OperationalSessionPresentation()

    @classmethod
    def from_thread(cls, project: Path, root: str, target,
                    agent: AgentDefinition | None = None) -> "MainScreen":
        screen = cls(project, agent, agent_session_id=target.name)
        screen.bind_thread(target, root)
        return screen

    def bind_thread(self, owner, root: str) -> None:
        from toad.thread_identity import ThreadIdentity
        with self.changing_identity():
            self._identity = ThreadIdentity(owner, root)

    def identity_changed(self, previous) -> None:
        if self.id is not None:
            self.app.session_navigation.sync_identity(self.id, previous.thread_name(), self.thread_identity.thread_name())
            self.app.session_tracker.bind_identity(self.id, previous.thread_name(), self.thread_identity.thread_name())

    @classmethod
    def opening(cls, request, origin, app) -> "MainScreen":
        # The request has only a name; bind the wire after its metadata read.
        screen = cls(request.project, origin.source._agent or app.agent_data,
                     agent_session_id=request.target)
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
        except Exception as error:
            self.opening_failed(error)
        else:
            self.content.finish(self, ReadyContent())

    def opening_failed(self, error: BaseException) -> None:
        self.content.finish(self, FailedContent(error))

    async def retire_presentation(self) -> None:
        # The departing scene is still committed here. Awaiting source/sidebar
        # retirement can publish a new layout which no longer contains it.
        self.presentation.capture_reader()
        await super().retire_presentation()
        await self.thread_sidebar.retire_presentation()
        await self.presentation.retire(self)

    def retained_native_presentations(self):
        resources = [(self, self.presentation)] if self.presentation.widget is not None else []
        sidebar = self.thread_sidebar
        if sidebar.panels_loaded:
            resources.append((self, sidebar))
        return tuple(resources)

    @property
    def session_disposition(self) -> SessionDisposition:
        return SessionDisposition.of(self.presentation.operational_agent)

    @property
    def agent_session_id(self) -> str | None:
        """The saved ACP session this screen owns."""
        return self._agent_session_id

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
        """The screen's title names the agent and the project it presents."""
        self.title = (f"{self._agent.name} {format_path(self.project_path)}"
                      if self._agent is not None else "")

    async def wait_content_ready(self) -> None:
        if self._closing or self._closed:
            return
        await self.content.wait(self)

    async def close_presentation(self) -> None:
        await self.thread_sidebar.evict()
        self.content.close(self)
        await self.presentation.close(self)

    @handles(core_events.CommsUpdated)
    async def on_comms_updated(self, event: CoreEventMessage) -> None:
        await ScreenCommsConsumer(self).dispatch(event.event.update)

    @handles(core_events.ExternalTranscriptChanged, core_events.SessionSelected)
    def external_transcript_changed(self, message: CoreEventMessage) -> None:
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
                from toad.thread_identity import ThreadIdentity
                self._identity = ThreadIdentity(event.thread, event.wire_root)
                if previous_root != self.coordination_root:
                    self.link_context_changed()
                if event.worktree is not None:
                    self.bind_project(Path(event.worktree))
                if self.id is not None:
                    self.app.session_navigation.sync_owner_root(self.id, self.coordination_root)
        await self.presentation.apply_coordination(self, event)

    @handles(core_events.AgentReady)
    async def on_session_attached(self, message: CoreEventMessage) -> None:
        event = cast(core_events.AgentReady, message.event)
        with self.changing_identity() as previous:
            self._identity = previous.with_session(event.session_id)
        await self.content.attached(self)

    @handles(core_events.AgentFail)
    def on_session_failure(self, message: CoreEventMessage) -> None:
        # A disconnected session is not a failed history-opening operation.
        # Its reason stays on the session; the opening line reads it there.
        self.content.render(self)

    _last_dm_target: str | None = None

    @property
    def navigation_target_name(self) -> str:
        return self.thread_identity.thread_name()

    @property
    def navigation_context(self) -> NavigationContext:
        assert self.id is not None
        return NavigationContext(self.app, self.id, self.project_path, self.thread_identity.thread_name())

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
            self.notify("Choose Direct messages from an agent's context menu",
                        title="Direct messages")
            return
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
        self.thread_sidebar.update_plan(message.event.entries)

    @handles(core_events.SessionTitleChanged)
    def on_session_title_changed(self, message: CoreEventMessage) -> None:
        """The user or the agent process named this session; the tab keeps it."""
        if self.id is not None:
            self.app.session_tracker.name_session(self.id, message.event.name)

    @handles(core_events.SessionThreadTitle)
    def on_session_thread_title(self, message: CoreEventMessage) -> None:
        """The thread presented a title; an authored name keeps the tab's label."""
        if (details := self.app.session_tracker.get_session(self.id)) is not None:
            if details.update_thread_title(message.event.title):
                self.app.session_tracker.events.publish(SessionChangedEvent(self.id))

    @handles(core_events.SessionSubtitleChanged)
    def on_session_subtitle_changed(self, message: CoreEventMessage) -> None:
        if self.id is not None:
            self.app.session_tracker.update_session(self.id, subtitle=message.event.subtitle)

    @handles(core_events.SessionPathChanged)
    def on_session_path_changed(self, message: CoreEventMessage) -> None:
        if self.id is not None:
            self.app.session_tracker.update_session(self.id, path=message.event.path)


    def on_mount(self) -> None:
        self.observe_core(self.app.events)
        self.observe_core(self.app.coordination_access.events)
        # Keep the screen-wide navigation row independent of sidebar geometry,
        # including when restoring a previously mounted owner tab.
        for tree in self.query("#project_directory_tree").results(DirectoryTree):
            tree.data_bind(path=MainScreen.project_path)
        for tree in self.query(DirectoryTree):
            tree.guide_depth = 3
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

    def sidebar_focus_target(self) -> Widget | None:
        conversation = self.query_one_optional(Conversation)
        if conversation is None:
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



class ScreenCommsConsumer(MroDispatch):
    def __init__(self, screen):
        self.screen = screen

    @handles(CoordinationChangedUpdate)
    async def coordination_changed(self, update: CoordinationChangedUpdate):
        await self.screen.on_coordination_update(update)
