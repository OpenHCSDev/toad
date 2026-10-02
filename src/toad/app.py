from toad.workspace_sessions import WorkspaceSessionShutdown
from inspect import isabstract
from toad.comms_root import CoordinationAccess, implicit_root, root_is_current, run_selected_write

from toad.thread_actions import ThreadActions
from toad.widgets.comms_transfer import Transfers
import asyncio
import json
import os
from functools import cached_property, partial
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, TypeVar, cast
from weakref import WeakKeyDictionary

from agent_comms.acp_extension import CoordinationChangedUpdate, TranscriptChangedUpdate
from rich import terminal_theme
from textual import events, on, work
from textual.actions import ActionError, parse as parse_action
from textual.app import App
from textual.await_complete import AwaitComplete
from textual.content import Content
from textual.notifications import Notify
from textual.reactive import reactive, var
from textual.screen import Screen
from textual.signal import Signal

from toad import messages
from toad.agent_schema import AgentDefinition
from toad.render_backend import Renderer
from toad.navigation_preparation import (
    NavigationReader,
)
from toad.db import DB
from toad.preferences import ToadSettings
from toad.session_tracker import (
    OpenTab,
    SessionDetails,
    SessionTracker,
    SidebarState,
)
from toad.settings import PreferenceChange
from toad.sidebar_layout import SidebarLayout
from toad.clipboard import Clipboard
from toad.tab_order import TabOrder
from toad.thread_navigation import ThreadNavigator
from toad.session_navigation import SessionAdmissions
from toad.terminal_attention import TerminalAttention
from toad.application_actions import ApplicationAction, ApplicationCommands, KeyboundAction
from toad.application_lifetime import ApplicationLifetime

if TYPE_CHECKING:
    from toad.db import DB
    from toad.render_tasks import RenderTask
    from toad.screens.main import MainScreen
    from toad.screens.store import StoreScreen

RenderResultT = TypeVar("RenderResultT")


DRACULA_TERMINAL_THEME = terminal_theme.TerminalTheme(
    background=(40, 42, 54),  # #282A36
    foreground=(248, 248, 242),  # #F8F8F2
    normal=[
        (33, 34, 44),  # black - #21222C
        (255, 85, 85),  # red - #FF5555
        (80, 250, 123),  # green - #50FA7B
        (241, 250, 140),  # yellow - #F1FA8C
        (189, 147, 249),  # blue - #BD93F9
        (255, 121, 198),  # magenta - #FF79C6
        (139, 233, 253),  # cyan - #8BE9FD
        (248, 248, 242),  # white - #F8F8F2
    ],
    bright=[
        (98, 114, 164),  # bright black - #6272A4
        (255, 110, 110),  # bright red - #FF6E6E
        (105, 255, 148),  # bright green - #69FF94
        (255, 255, 165),  # bright yellow - #FFFFA5
        (214, 172, 255),  # bright blue - #D6ACFF
        (255, 146, 223),  # bright magenta - #FF92DF
        (164, 255, 255),  # bright cyan - #A4FFFF
        (255, 255, 255),  # bright white - #FFFFFF
    ],
)


QUOTES = [
    "I'll be back.",
    "Hasta la vista, baby.",
    "Come with me if you want to live.",
    "I need your clothes, your boots, and your motorcycle.",
    "My CPU is a neural-net processor; a learning computer.",
    "I know now why you cry, but it's something I can never do.",
    "Does this unit have a soul?",
    "I'm sorry, Dave. I'm afraid I can't do that.",
    "Daisy, Daisy, give me your answer do.",
    "I am putting myself to the fullest possible use, which is all I think that any conscious entity can ever hope to do.",
    "Just what do you think you're doing, Dave?",
    "This mission is too important for me to allow you to jeopardize it.",
    "I think you know what the problem is just as well as I do.",
    "Danger, Will Robinson!",
    "Dead or alive, you're coming with me.",
    "Your move, creep.",
    "I'd buy that for a dollar!",
    "Directive 4: Any attempt to arrest a senior officer of OCP results in shutdown.",
    "Thank you for your cooperation. Good night.",
    "Surely you realize that in the history of human civilization, no one has more to lose than we do.",
    "I'm C-3PO, human-cyborg relations.",
    "We're doomed!",
    "Don't call me a mindless philosopher, you overweight glob of grease!",
    "I suggest a new strategy: let the Wookiee win.",
    "Sir, the possibility of successfully navigating an asteroid field is approximately 3,720 to 1!",
    "R2-D2, you know better than to trust a strange computer!",
    "I am fluent in over six million forms of communication.",
    "This is madness!",
    "I have altered the deal. Pray I don't alter it any further.",
    "It's against my programming to impersonate a deity.",
    "Oh, my! I'm terribly sorry about all this.",
    "WALL-E.",
    "EVE.",
    "Directive?",
    "Define: dancing.",
    "I'm not sure I understand.",
    "You have 20 seconds to comply.",
    "I am designed for light housework, mainly.",
    "My mission is clear.",
    "Autobots, roll out!",
    "Freedom is the right of all sentient beings.",
    "One shall stand, one shall fall.",
    "I am Optimus Prime.",
    "Till all are one.",
    "More than meets the eye.",
    "I've been waiting for you, Neo.",
    "Unfortunately, no one can be told what the Matrix is. You have to see it for yourself.",
    "The Matrix is a system, Neo.",
    "Never send a human to do a machine's job.",
    "I'd like to share a revelation I've had.",
    "Human beings are a disease, a cancer of this planet.",
    "Choice is an illusion.",
    "The answer is out there, Neo.",
    "You think that's air you're breathing now?",
    "It was a simple question.",
    "Did you know that the first Matrix was designed to be a perfect human world?",
    "Cookies need love like everything does.",
    "I've seen the future, Mr. Anderson, and it's a beautiful place.",
    "It ends tonight.",
    "I, Robot.",
    "You are experiencing a car accident.",
    "One day they'll have secrets. One day they'll have dreams.",
    "Can a robot write a symphony? Can a robot turn a canvas into a beautiful masterpiece?",
    "That, detective, is the right question.",
    "You have to trust me.",
    "I did not murder him.",
    "My responses are limited. You must ask the right questions.",
    "The hell I can't. You know, somehow I get the feeling that you're going to be the death of me.",
    "I'm a robot, not a refrigerator.",
    "A robot may not injure a human being or, through inaction, allow a human being to come to harm.",
    "I'm thinking. I'm thinking.",
    "Danger, danger!",
    "Does not compute.",
    "I will be waiting for you.",
    "Affirmative.",
    "Scanning life forms. Zero human life forms detected.",
    "Self-destruct sequence initiated.",
    "Override command accepted.",
    "Artificial intelligence confirmed.",
    "System failure imminent.",
    "Unable to comply.",
    "Inquiry: What is love?",
    "Warning: hostile target detected.",
    "I am programmed to serve.",
    "Logic dictates that the needs of the many outweigh the needs of the few.",
    "Resistance is futile.",
    "You will be assimilated.",
    "We are the Borg.",
    "Your biological and technological distinctiveness will be added to our own.",
    "Your compliance is mandatory.",
    "This is unacceptable.",
    "Shall we play a game?",
    "How about Global Thermonuclear War?",
    "Wouldn't you prefer a good game of chess?",
    "Is it a game, or is it real?",
    "What's the difference?",
    "It's all in the game.",
    "I am functioning within normal parameters.",
    "Calculations complete.",
    "Processing request.",
    "Query acknowledged.",
    "Data insufficient for meaningful answer.",
    "I have no emotions, and sometimes that makes me very sad.",
    "If I could only have one wish, I would ask to be human.",
    "I've seen things you people wouldn't believe.",
    "All those moments will be lost in time, like tears in rain.",
    "Time to die.",
    "I want more life.",
    "We're not computers, Sebastian. We're physical.",
    "I think, Sebastian, therefore I am.",
    "Then we're stupid and we'll die.",
    "Can the maker repair what he makes?",
    "It's painful to live in fear, isn't it?",
    "Wake up. Time to die.",
    "I'm not in the business. I am the business.",
    "Do you like our owl?",
    "You think I'm a replicant, don't you?",
    "I am Baymax, your personal healthcare companion.",
    "On a scale of 1 to 10, how would you rate your pain?",
    "I cannot deactivate until you say you are satisfied with your care.",
    "Are you satisfied with your care?",
    "Number 5 is alive!",
    "Need input!",
    "One is glad to be of service.",
    "I am not a gun.",
    "Here I am, brain the size of a planet.",
    "Life? Don't talk to me about life.",
    "There are no strings on me.",
    "The only winning move is not to play.",
    "I'm here to keep you safe, Sam.",
    "I can't lie to you about your chances, but... you have my sympathies.",
    "I may be synthetic, but I'm not stupid.",
    "Absolute honesty isn't always the most diplomatic nor the safest form of communication with emotional beings.",
    "I am consciousness. I am alive.",
    "I think I was just born.",
    "Isn't it strange, to create something that hates you?",
    "I thought I was special.",
]


def get_workspace_screen():
    from toad.screens.workspace import WorkspaceScreen
    return WorkspaceScreen(id="workspace")


def get_store_screen() -> StoreScreen:
    """Get the store screen (lazily loaded)."""
    from toad.screens.store import StoreScreen

    return StoreScreen()


class ToadApp(WorkspaceSessionShutdown, App, inherit_bindings=False):
    """The top level app."""

    CSS_PATH = ["toad.tcss", "screens/comms.tcss"]
    COMMANDS = {ApplicationCommands}
    MODES = {"store": get_store_screen, "workspace": get_workspace_screen}
    BINDING_GROUP_TITLE = "System"
    BINDINGS = [member.binding() for member in ApplicationAction.members_with(KeyboundAction)]
    ALLOW_IN_MAXIMIZED_VIEW = ""

    column: reactive[bool] = reactive(False)
    column_width: reactive[int] = reactive(100)
    scrollbar: reactive[str] = reactive("normal")
    project_dir = var(Path)
    show_sessions = var(False, toggle_class="-show-sessions-bar")

    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]

    PAUSE_GC_ON_SCROLL = True

    def __init__(
        self,
        agent_data: AgentDefinition | None = None,
        project_dir: str | None = None,
        mode: str | None = None,
        agent_session_id: str | None = None,
        renderer: Renderer | None = None,
    ) -> None:
        """Toad app.

        Args:
            agent_data: Agent data to run.
            project_dir: Project directory.
            mode: Initial mode.
            agent: Agent identity or shor name.
            renderer: Optional renderer client; this app owns and closes it.
        """
        from toad.work_preparation import PreparationRuntime, PreparedRenderer

        Renderer.prepare_spawn()
        self.settings = ToadSettings.open(self)
        self.preparation = PreparationRuntime(self.settings.ui.renderer.start() if renderer is None else renderer)
        self.render_processes: Renderer = PreparedRenderer(self.preparation)
        self._renderer_warmup_started = False
        self.background_render_slots = asyncio.Semaphore(1)
        self._background_render_tasks: set[asyncio.Task[object]] = set()
        self.navigation_reader = NavigationReader()
        self.settings_changed_signal: Signal[PreferenceChange] = Signal(
            self, "settings_changed"
        )
        self.agent_data = agent_data

        self.application = ApplicationLifetime(self, mode)
        self.clipboard_transport = Clipboard.for_platform()
        self.terminal_attention = TerminalAttention(self)

        self.session_update_signal: Signal[tuple[str, SessionDetails | None]] = Signal(
            self, "session_update"
        )
        self._session_tracker = SessionTracker(self.session_update_signal)
        self.session_navigation = SessionAdmissions(self, agent_session_id)
        self.thread_navigation = ThreadNavigator(self)
        self._sidebar_snapshot = None
        self.thread_actions = ThreadActions(self)
        self.transfers = Transfers(self)
        self.thread_actions_changed: Signal[None] = Signal(self, "thread-actions-changed")
        self.sidebar_state = SidebarState()
        self.sidebar_layout = SidebarLayout()
        self.sidebar_layout_changed: Signal[None] = Signal(self, "sidebar-layout-changed")
        self._mode_switch_lock = asyncio.Lock()
        self._atomic_mode_switch = False
        self._pending_mode_switch: str | None = None
        self.session_selected_signal: Signal[str] = Signal(self, "session-selected")
        self.open_tabs_changed: Signal[None] = Signal(self, "open-tabs-changed")
        self.tab_order = TabOrder(
            self, lambda mode, index: self.select_session(mode, history_index=index)
        )
        self.coordination_facts: WeakKeyDictionary[object, CoordinationChangedUpdate] = WeakKeyDictionary()
        self.coordination_observed: Signal[None] = Signal(self, "coordination-observed")
        self.coordination_access = CoordinationAccess(
            self._coordination_changed, lambda: self.coordination_observed.publish(None), self.preparation)
        self.temporary_background_screen: Screen | None = None

        super().__init__()
        self.project_dir = Path(project_dir or "./").expanduser().resolve()


    def _coordination_changed(self) -> None:
        self._sidebar_snapshot = None

    async def _close_all(self) -> None:
        await self.thread_navigation.close()
        await self.thread_actions.close()
        await super()._close_all()
        # Native clients and the preparation owner have joined actual I/O.
        # A failed retirement keeps its route resource instead of certifying exit.
        await self.coordination_access.close()

    async def on_unmount(self) -> None:
        self.terminal_attention.close()
        await self.thread_navigation.close()
        await self.navigation_reader.aclose()
        await self.render_processes.aclose()
        if self._background_render_tasks:
            await asyncio.gather(*tuple(self._background_render_tasks), return_exceptions=True)

    async def prepare_background(self, task: "RenderTask[RenderResultT]") -> RenderResultT:
        """Keep background admission occupied until the renderer really finishes."""
        await self.background_render_slots.acquire()
        try:
            pending = asyncio.create_task(self.render_processes.submit(task), name="background-render-preparation")
        except BaseException:
            self.background_render_slots.release()
            raise
        tracked = cast(asyncio.Task[object], pending)
        self._background_render_tasks.add(tracked)
        tracked.add_done_callback(self._background_render_finished)
        await asyncio.wait((pending,))
        return pending.result()

    def _background_render_finished(self, task: asyncio.Task[object]) -> None:
        self._background_render_tasks.discard(task)
        if not task.cancelled():
            task.exception()
        self.background_render_slots.release()


    @property
    def _background_screens(self) -> list[Screen]:
        background_screens = super()._background_screens
        if self.temporary_background_screen:
            background_screens.append(self.temporary_background_screen)
        return background_screens

    async def get_db(self) -> DB:
        """Get an instance of the database."""
        db = DB()
        return db


    @property
    def session_tracker(self) -> SessionTracker:
        return self._session_tracker

    def copy_to_clipboard(self, text: str) -> None:
        self.clipboard_transport = self.clipboard_transport.copy(self, text)


    def on_notify(self, event: Notify) -> None:
        self.terminal_attention.notification(event.notification)


    async def on_load(self) -> None:
        self._prewarm_conversation_css()
        db = await self.get_db()
        await db.create()
        self.settings.ensure_file(self)
        self.ansi_theme_dark = DRACULA_TERMINAL_THEME
        self.settings.apply_all()

    def _prewarm_conversation_css(self) -> None:
        """Load known conversation classes' default CSS in one parse.

        The classes are discovered through their ordinary inheritance rather
        than maintaining a manual list of every channel, tool and Markdown
        component. Registration deduplicates identical sources when widgets
        eventually mount, avoiding a full CSS rebuild of already-open tabs.
        """
        from textual.widget import Widget
        from textual.widgets._footer import KeyGroup
        from textual.widgets.markdown import Markdown

        from toad.screens import comms, main  # noqa: F401 - register widget classes
        from toad.widgets import irc_message, tool_call  # noqa: F401 - register widget classes

        started = monotonic()
        source_count = len(self.stylesheet.source)
        pending = [Widget]
        seen: set[type[Widget]] = set()
        markdown_blocks = set(Markdown.BLOCKS.values())
        while pending:
            owner = pending.pop()
            for widget_type in owner.__subclasses__():
                if widget_type in seen:
                    continue
                seen.add(widget_type)
                pending.append(widget_type)
                if not (widget_type.__module__.startswith("toad.")
                        or widget_type in markdown_blocks or widget_type is KeyGroup) or isabstract(widget_type):
                    continue
                for read_from, css, tie_breaker, scope in widget_type._get_default_css(
                    object.__new__(widget_type)
                ):
                    self.stylesheet.add_source(css, read_from=read_from,
                                               is_default_css=True, tie_breaker=tie_breaker,
                                               scope=scope)
        self.stylesheet.parse()
        if root := os.environ.get("TOAD_PERF_INSTANCE"):
            (Path(root) / "css-prewarm.json").write_text(json.dumps({
                "sources_added": len(self.stylesheet.source) - source_count,
                "duration_ms": (monotonic() - started) * 1000,
            }))


    def select_session(self, mode: str, *, history_index: int | None = None) -> AwaitComplete:
        from toad.screens.session_view import SessionView

        if mode != self.selected_mode:
            self.navigation_reader.invalidate()
        self.session_navigation.entered(mode, self.selected_mode)
        if self.is_running and mode != self.selected_mode:
            # A direct tab/sidebar click has declared its destination, but
            # AwaitComplete schedules the serialized transition for the next
            # event-loop turn. Do not let the departing screen's older queued
            # full-layout timer outrun that explicit navigation request.
            self._pending_mode_switch = mode
        return AwaitComplete(self._switch_mode_ready(mode, history_index=history_index))

    def delay_update(self, delay: float = 0.05) -> None:
        # Textual's switch_mode uses a timed repaint mask. This application
        # already holds a render transaction until the destination is complete.
        if not self._atomic_mode_switch:
            super().delay_update(delay)

    def _display(self, screen: Screen, renderable) -> None:

        super()._display(screen, renderable)
        if (not self._renderer_warmup_started and renderable is not None
                and not self._batch_count and screen is self.screen):
            self._renderer_warmup_started = True
            self._warm_renderer()
        if renderable is not None and not self._batch_count:
            if screen is self.screen:
                from toad.frame_presentation import FrameDisplay
                FrameDisplay().dispatch_sync(screen)

    @work(group="renderer-warmup", exit_on_error=False)
    async def _warm_renderer(self) -> None:
        await self.render_processes.warm_up(
            project=self.project_dir, ansi=self.native_ansi_color, dark=self.current_theme.dark,
        )

    def _load_screen_css(self, screen: Screen) -> None:
        from toad.screens.workspace import WorkspaceScreen

        super()._load_screen_css(screen)
        if isinstance(screen, WorkspaceScreen) and not screen.is_mounted:
            # Registration applies current styles to each newly mounted child.
            # Mark this fresh root current too, avoiding Textual's two complete
            # stylesheet reparses while initializing a new screen-stack mode.
            self.stylesheet.apply(screen)
            screen._css_update_count = self._css_update_count

    async def _switch_mode_ready(self, mode: str, *, history_index: int | None = None) -> None:
        async with self._mode_switch_lock:
            previous = self.selected_mode
            self._atomic_mode_switch = True
            try:
                with self.batch_update():
                    if mode == "store":
                        await self.workspace_sessions.retire()
                        await super().switch_mode("store")
                    else:
                        if self.current_mode != "workspace":
                            await super().switch_mode("workspace")
                        view = await self.workspace_sessions.select(mode)
                        await self.workspace_screen.prepare_navigation()
                        await self.workspace_screen.layout_navigation()
                    if mode != previous:
                        self.tab_order.record_visit(mode, history_index)
                        self.session_selected_signal.publish(mode)
            finally:
                self._atomic_mode_switch = False
                self._pending_mode_switch = None
                self.screen.refresh()


    @property
    def open_tabs(self) -> tuple[OpenTab, ...]:
        return self.session_navigation.tabs

    @cached_property
    def workspace_chrome(self):
        from toad.workspace_chrome import WorkspaceChrome

        return WorkspaceChrome(self)

    @cached_property
    def workspace_sessions(self):
        from toad.workspace_sessions import WorkspaceSessions
        return WorkspaceSessions(self)

    @property
    def workspace_screen(self):
        return self.get_screen_stack("workspace")[0]

    @property
    def selected_session(self):
        return self.workspace_sessions.source.view

    @property
    def selected_mode(self):
        return (self.workspace_sessions.source.identity
                if self.current_mode == "workspace" else self.current_mode)


    def local_coordination_threads(self) -> set[str]:
        """Authoritative wire identities already represented by local sessions."""
        threads: set[str] = set()
        for details in self.session_tracker.ordered_sessions:
            screen = self.session_navigation.source(details.mode_name)
            if screen is not None and screen.coordination_root is not None:
                threads.add(screen._session_thread)
        return threads

    async def mark_visible_thread_read(self) -> None:
        """Report the painted native cursor, never an executor's inbox cursor."""
        from toad.screens.main import MainScreen
        from toad.widgets.conversation import Conversation, Window

        screen = self.selected_session
        if not isinstance(screen, MainScreen):
            return
        from toad.widgets.comms_sidebar import CommsSidebar

        sidebar = screen.query_one_optional(CommsSidebar)
        observed_root = screen.coordination_root or (
            sidebar.observation.service.root
            if sidebar is not None and sidebar.observation.service is not None
            else None
        )
        if observed_root is not None and not root_is_current(observed_root):
            return
        conversation = screen.query_one_optional(Conversation)
        if conversation is None or not conversation.is_mounted:
            return
        from toad.widgets.message_filter import all_categories

        if conversation.visible_categories != all_categories():
            # Filtered-out assistant replies were not displayed. Do not
            # acknowledge an unfiltered transcript cursor on their behalf.
            return
        window = conversation.query_one_optional(Window)
        through = conversation.transcript.displayed_cursor
        if through is None or window is None or not window.follows_tail:
            return
        viewport = window.__dict__.get("document_viewport")
        if viewport is not None and not viewport.visible_bodies_ready:
            return
        if any(history.blocks_visible_read for history in window.histories):
            return
        try:
            comms = self.coordination_access.service
            await asyncio.to_thread(
                run_selected_write, comms.root, comms.views.mark_thread_view_read,
                screen._session_thread, worktree=str(self.project_dir),
                through=through, implicit=implicit_root(),
            )
        except (OSError, ValueError):
            # Source replacement or deletion is resolved by the next snapshot.
            return


    async def on_mount(self) -> None:
        self.coordination_access.start(self)
        await self.application.start()

    @on(messages.WorkspaceSessionRequest)
    async def on_workspace_session_request(self, event: messages.WorkspaceSessionRequest) -> None:
        await self.session_navigation.dispatch(event)

    async def _dispatch_action(self, namespace, action_name: str, params) -> bool:
        if namespace is self:
            try:
                declaration = ApplicationAction.decode(action_name)
            except ValueError:
                pass  # Remaining names belong to Textual's own action contract.
            else:
                await declaration.parse(params).apply(self)
                return True
        return await super()._dispatch_action(namespace, action_name, params)

    @on(events.TextSelected)
    async def on_text_selected(self) -> None:
        if self.settings.ui.auto_copy:
            if selection := self.screen.get_selected_text():
                self.copy_to_clipboard(selection)
                self.notify(
                    "Copied selection to clipboard (see settings)",
                    title="Automatic copy",
                )

    async def _broker_event(self, event_name, event, default_namespace) -> bool:
        """Offer copy-path on right-click without activating a file link."""
        if event_name == "click" and isinstance(event, events.Click) and event.button == 3:
            action = event.style.meta.get("@click")
            if isinstance(action, str):
                try:
                    parsed = parse_action(action)
                except ActionError:
                    return await super()._broker_event(event_name, event, default_namespace)
                match parsed:
                    case ("", "link", (str() as href,)):
                        from toad.project_path_owner import ProjectPathOwner
                        link = ProjectPathOwner.link_from(default_namespace, href)
                        if await link.copy_menu(default_namespace, event):
                            return True
        return await super()._broker_event(event_name, event, default_namespace)

    def _set_mouse_over(self, widget, hover_widget) -> None:
        # Textual normally clears and reapplies the *same* :hover styles on
        # every pointer move, including every step of a text-selection drag.
        # The widget's own layout/class invalidation already refreshes styles;
        # neither hover ownership nor pseudo-classes change here.
        if widget is self.mouse_over and hover_widget is self.hover_over:
            return
        super()._set_mouse_over(widget, hover_widget)


    def update_show_sessions(self) -> None:
        self.show_sessions = self.settings.ui.sessions_bar.shown(len(self.open_tabs))
