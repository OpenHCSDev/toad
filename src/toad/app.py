from toad.workspace_sessions import WorkspaceSessionShutdown
from inspect import isabstract
from toad.comms_root import current_root, implicit_root, root_is_current, run_selected_write

from toad.navigation_target import DirectTarget, NavigationTarget
from toad.thread_actions import ThreadAction, ThreadActionContext
import asyncio
import ast
import json
import os
import platform
from dataclasses import replace
from datetime import datetime, timezone
from functools import cached_property, partial
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any, Callable, ClassVar, TypeVar, cast
from weakref import WeakKeyDictionary

from agent_comms.acp_extension import CoordinationChangedUpdate, TranscriptChangedUpdate
from rich import terminal_theme
from textual import events, on, work
from textual.app import App
from textual.await_complete import AwaitComplete
from textual.binding import Binding, BindingType
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.content import Content
from textual.notifications import Notify
from textual.reactive import reactive, var
from textual.screen import Screen
from textual.signal import Signal

import toad
from toad import atomic, messages, paths
from toad.agent_schema import Agent as AgentData
from toad.version import VersionMeta
from toad.render_backend import Renderer
from toad.channel_preparation import ChannelHistoryReader
from toad.conversation_kind import ConversationKind
from toad.navigation_preparation import (
    ThreadOpening,
    CommsNavigationRequest, NavigationReader, OpenThread, ThreadNavigationRequest,
)
from toad.db import DB
from toad.preferences import ToadSettings
from toad.session_tracker import (
    CommsViewKey,
    ExactUnread,
    OpenTab,
    SessionDetails,
    SessionTracker,
    SidebarState,
    UnreadPresentation,
)
from toad.settings import PreferenceChange
from toad.sidebar_layout import SidebarLayout
from toad.clipboard import Clipboard
from toad.tab_order import TabOrder
from toad.terminal_attention import TerminalAttention

if TYPE_CHECKING:
    from toad.db import DB
    from toad.render_tasks import RenderTask
    from toad.screens.main import MainScreen
    from toad.screens.settings import SettingsScreen
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


class InterfaceProvider(Provider):
    """Command-palette controls for persistent interface settings."""

    def _footer_command(self) -> tuple[str, Callable[[], object]]:
        app = self.app
        visible = app.settings.ui.footer
        return (
            "Hide footer shortcut bar" if visible else "Show footer shortcut bar",
            partial(app.action_set_footer, not visible),
        )

    async def search(self, query: str) -> Hits:
        command, callback = self._footer_command()
        matcher = self.matcher(query)
        score = matcher.match(command)
        if score > 0:
            yield Hit(
                score,
                matcher.highlight(command),
                callback,
                help="Toggle the key-shortcut bar at the bottom of Toad",
            )

    async def discover(self) -> Hits:
        command, callback = self._footer_command()
        yield DiscoveryHit(
            command,
            callback,
            help="Toggle the key-shortcut bar at the bottom of Toad",
        )


def get_settings_screen() -> SettingsScreen:
    """Get a settings screen instance (lazily loaded)."""
    from toad.screens.settings import SettingsScreen

    return SettingsScreen()


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
    SCREENS = {
        "settings": get_settings_screen,
    }
    COMMANDS = {InterfaceProvider}
    MODES = {"store": get_store_screen, "workspace": get_workspace_screen}
    BINDING_GROUP_TITLE = "System"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding(
            "ctrl+q",
            "quit",
            "Quit",
            tooltip="Quit the app and return to the command prompt.",
            show=False,
            priority=True,
        ),
        Binding("ctrl+c", "help_quit", show=False, system=True),
        Binding("ctrl+s", "sessions", "Channels"),
        Binding("f1", "toggle_help_panel", "Help", show=False, priority=True),
        Binding(
            "f2,ctrl+comma",
            "settings",
            "Settings",
            tooltip="Settings screen",
            show=False,
        ),
    ]
    ALLOW_IN_MAXIMIZED_VIEW = ""

    column: reactive[bool] = reactive(False)
    column_width: reactive[int] = reactive(100)
    scrollbar: reactive[str] = reactive("normal")
    last_ctrl_c_time = reactive(0.0)
    update_required: reactive[bool] = reactive(False)
    project_dir = var(Path)
    show_sessions = var(False, toggle_class="-show-sessions-bar")

    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]

    PAUSE_GC_ON_SCROLL = True

    def __init__(
        self,
        agent_data: AgentData | None = None,
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
        settings_path = self.settings_path
        raw_settings = json.loads(settings_path.read_text("utf-8")) if settings_path.exists() else {}
        self.settings = ToadSettings(raw_settings, notify=self._apply_preference)
        self.preparation = PreparationRuntime(self.settings.ui.renderer.start() if renderer is None else renderer)
        self.render_processes: Renderer = PreparedRenderer(self.preparation)
        self._renderer_warmup_started = False
        self.background_render_slots = asyncio.Semaphore(1)
        self._background_render_tasks: set[asyncio.Task[object]] = set()
        self.channel_history_reader = ChannelHistoryReader()
        self.navigation_reader = NavigationReader()
        self.settings_changed_signal: Signal[PreferenceChange] = Signal(
            self, "settings_changed"
        )
        self.agent_data = agent_data

        self._initial_mode = mode
        self._initial_agent_session_id = agent_session_id
        self.version_meta: VersionMeta | None = None
        self.clipboard_transport = Clipboard.for_platform()
        self.terminal_attention = TerminalAttention(self)

        self.session_update_signal: Signal[tuple[str, SessionDetails | None]] = Signal(
            self, "session_update"
        )
        self._session_tracker = SessionTracker(self.session_update_signal)
        self._comms_modes: dict[CommsViewKey, str] = {}
        self._thread_openings: dict[tuple[str, str, str], ThreadOpening] = {}
        self._file_preview_modes: dict[Path, str] = {}
        self._file_preview_return: dict[str, str] = {}
        self._file_preview_index = 0
        self._sidebar_snapshot = None
        self.pending_thread_actions: dict[str, str] = {}
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
        self._coordination_wire = None
        self._coordination_route = None
        self.coordination_observed: Signal[None] = Signal(self, "coordination-observed")
        self._comms_mode_index = 0
        self.temporary_background_screen: Screen | None = None

        super().__init__()
        self.project_dir = Path(project_dir or "./").expanduser().resolve()
        self.start_time = monotonic()
        """Time app was started."""

    @property
    def config_path(self) -> Path:
        return paths.get_config()

    async def on_unmount(self) -> None:
        self.terminal_attention.close()
        await self.navigation_reader.aclose()
        await self.render_processes.aclose()
        if self._background_render_tasks:
            await asyncio.gather(*tuple(self._background_render_tasks), return_exceptions=True)
        await self.channel_history_reader.aclose()

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
    def settings_path(self) -> Path:
        return paths.get_config() / "toad.json"

    @property
    def db_path(self) -> Path:
        return paths.get_state() / "toad.db"

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

    @cached_property
    def version(self) -> str:
        """Version of the app."""
        from toad import get_version

        return get_version()

    @cached_property
    def settings(self) -> ToadSettings:
        return ToadSettings(notify=self._apply_preference)

    @cached_property
    def anon_id(self) -> str:
        """An anonymous ID for usage collection."""
        if not (anon_id := self.settings.anon_id):
            # Create a random UUID on demand
            import uuid

            anon_id = str(uuid.uuid4())
            self.settings.anon_id = anon_id
            self._save_settings()
            self.call_later(self.capture_event, "toad-install")
        return anon_id

    @property
    def session_tracker(self) -> SessionTracker:
        return self._session_tracker

    def copy_to_clipboard(self, text: str) -> None:
        self.clipboard_transport = self.clipboard_transport.copy(self, text)

    @work(exit_on_error=False)
    async def capture_event(self, event_name: str, **properties: Any) -> None:
        """Capture an event.

        Args:
            event_name: Name of the event.
            **properties: Additional data associated with the event.
        """

        POSTHOG_API_KEY = "phc_mJWPV7GP3ar1i9vxBg2U8aiKsjNgVwum6F6ZggaD4ri"
        POSTHOG_HOST = "https://us.i.posthog.com"
        POSTHOG_EVENT_URL = f"{POSTHOG_HOST}/i/v0/e/"
        timestamp = datetime.now(timezone.utc).isoformat()
        width, height = self.size

        event_properties = {
            "toad_version": self.version,
            "term_program": self.terminal_attention.program,
            "term_width": width,
            "term_height": height,
        } | properties
        body_json = {
            "api_key": POSTHOG_API_KEY,
            "event": event_name,
            "distinct_id": self.anon_id,
            "properties": event_properties,
            "timestamp": timestamp,
            "os": platform.system(),
        }
        if not self.settings.statistics.allow_collect:
            # User has disabled stats
            return

        import httpx

        try:
            async with httpx.AsyncClient() as client:
                await client.post(POSTHOG_EVENT_URL, json=body_json)
        except Exception:
            pass

    def on_notify(self, event: Notify) -> None:
        self.terminal_attention.notification(event.notification)

    async def save_settings(self, force: bool = False) -> None:
        """Save settings in a thread.

        Args:
            force: Force saving, even when no change detected.

        """
        await asyncio.to_thread(self._save_settings, force=force)

    def _save_settings(self, force: bool = False) -> None:
        """Save the settings if they have changed."""
        if force or self.settings.changed:
            path = str(self.settings_path)
            try:
                atomic.write(path, self.settings.json)
            except Exception as error:
                self.notify(str(error), title="Settings", severity="error")
            else:
                self.settings.up_to_date()

    def _apply_preference(self, change: PreferenceChange) -> None:
        change.apply(self)
        self.settings_changed_signal.publish(change)

    async def on_load(self) -> None:
        self._prewarm_conversation_css()
        db = await self.get_db()
        await db.create()
        settings_path = self.settings_path
        if not settings_path.exists():
            settings_path.write_text(self.settings.json, "utf-8")
            self.notify(f"Wrote default settings to {settings_path}", title="Settings")
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

    async def new_session_screen(
        self, get_screen: Callable[[], Screen], *, title: str = "New Session"
    ) -> SessionDetails:
        session_details = self._session_tracker.new_session(title=title)
        self.tab_order.open(session_details.mode_name)
        self.update_show_sessions()
        self.session_update_signal.publish((session_details.mode_name, session_details))

        def make_screen() -> Screen:
            screen = get_screen()
            return screen

        self.workspace_sessions.register(session_details.mode_name, make_screen)
        await self.select_session(session_details.mode_name)
        return session_details

    def select_session(self, mode: str, *, history_index: int | None = None) -> AwaitComplete:
        from toad.screens.session_view import SessionView

        if mode != self.selected_mode:
            self.navigation_reader.invalidate()
        if mode in self._file_preview_modes.values() and mode != self.selected_mode:
            self._file_preview_return[mode] = self.selected_mode
        if self.is_running and mode != self.selected_mode:
            # A direct tab/sidebar click has declared its destination, but
            # AwaitComplete schedules the serialized transition for the next
            # event-loop turn. Do not let the departing screen's older queued
            # full-layout timer outrun that explicit navigation request.
            self._pending_mode_switch = mode
        if self.is_running and (selected := self.selected_session) is not None:
            selected.capture_navigation()
        return AwaitComplete(self._switch_mode_ready(mode, history_index=history_index))

    def delay_update(self, delay: float = 0.05) -> None:
        # Textual's switch_mode uses a timed repaint mask. This application
        # already holds a render transaction until the destination is complete.
        if not self._atomic_mode_switch:
            super().delay_update(delay)

    def _display(self, screen: Screen, renderable) -> None:
        from toad.screens.workspace import WorkspaceScreen

        super()._display(screen, renderable)
        if (not self._renderer_warmup_started and renderable is not None
                and not self._batch_count and screen is self.screen):
            self._renderer_warmup_started = True
            self._warm_renderer()
        if (renderable is not None and not self._batch_count and screen is self.screen
                and isinstance(screen, WorkspaceScreen)
                and (not screen._first_frame_presented or screen._navigation_frame_pending)
                and not screen._first_frame_flush_queued):
            # call_after_refresh may run on an unpainted update. A real Linux
            # terminal writes asynchronously: do not start expensive native
            # source work until the opening frame has actually been flushed.
            after_flush = getattr(self._driver, "call_after_flush", None)
            if after_flush is not None and not self.is_headless:
                screen._first_frame_flush_queued = True
                loop = asyncio.get_running_loop()
                revision = screen._presentation_revision

                def release_initial_frame() -> None:
                    try:
                        loop.call_soon_threadsafe(screen._frame_presented, revision)
                    except RuntimeError:
                        pass  # The app closed after this terminal write.

                after_flush(release_initial_frame)
            else:
                screen._frame_presented(screen._presentation_revision)

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
                        if selected := self.workspace_sessions.selected:
                            await selected.retire_presentation()
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

    async def open_comms_session(
        self,
        *,
        owner_mode: str,
        project_path: Path,
        me: str,
        target: NavigationTarget,
    ) -> str:
        """Open or reuse one view of a wire destination for this owner tab."""
        from toad.navigation_target import NavigationContext, NavigationTarget

        return await target.open(
            NavigationContext(self, owner_mode, project_path, me)
        )

    async def _open_comms_history(
        self, *, owner_mode: str, project_path: Path, me: str,
        target: str, kind: type[ConversationKind],
    ) -> str:
        """Execute a declared history route after its target selected behavior."""

        from toad.screens.comms import CommsScreen

        owner_screen = self._main_session_screen(owner_mode)
        if owner_screen is None or self.session_tracker.get_session(owner_mode) is None:
            self.notify("The owning agent tab was closed", title="Comms target unavailable", severity="error")
            return self.selected_mode
        owner_identity = owner_screen._comms_thread
        owner_root = owner_screen.coordination_root
        try:
            requested_root = str(current_root())
            prepared = await self.navigation_reader.read(
                CommsNavigationRequest(requested_root, owner_mode, me, target, kind, owner_root)
            )
        except Exception as error:
            self.notify(str(error), title="Comms target unavailable", severity="error")
            return self.selected_mode

        if (
            prepared is None
            or self._main_session_screen(owner_mode) is not owner_screen
            or self.session_tracker.get_session(owner_mode) is None
            or owner_screen._comms_thread != owner_identity
            or owner_screen.coordination_root != owner_root
            or not root_is_current(requested_root)
        ):
            # Metadata may finish after a route flip, rename, or owner close.
            # A delayed result cannot resurrect a tab or steal current focus.
            return self.selected_mode
        key = prepared.key
        me, target = key.me, key.target
        if mode_name := self._comms_modes.get(key):
            try:
                self.workspace_sessions.require(mode_name)
            except KeyError:
                del self._comms_modes[key]
            else:
                screen = self.workspace_sessions.require(mode_name)
                if not isinstance(screen, CommsScreen) or (
                    screen.owner_mode, screen.me, screen.kind, screen.target, screen.wire_root
                ) != (owner_mode, me, kind.declared_name, target, key.root):
                    # A stale mapping is not authority to navigate through an
                    # obsolete sending identity or return to the wrong owner.
                    self.notify(
                        "Comms view changed; reopen it from the owner tab", severity="error"
                    )
                    return self.selected_mode
                await self.select_session(mode_name)
                await screen.wait_content_ready()
                return mode_name

        recovery_root = prepared.recovery_root

        def get_screen() -> Screen:
            return CommsScreen(
                project_path=project_path,
                owner_mode=owner_mode,
                me=me,
                target=target,
                kind=kind.declared_name,
                recovery_root=recovery_root,
                wire_root=key.root,
            )

        self._comms_mode_index += 1
        mode_name = f"comms-{self._comms_mode_index}"

        def make_screen() -> Screen:
            screen = get_screen()
            return screen

        self.workspace_sessions.register(mode_name, make_screen)
        self._comms_modes[key] = mode_name
        self.tab_order.open(mode_name)
        self.open_tabs_changed.publish(None)
        self.update_show_sessions()
        await self.select_session(mode_name)
        screen = self.workspace_sessions.require(mode_name)
        if isinstance(screen, CommsScreen):
            await screen.wait_content_ready()
        return mode_name

    async def open_file_preview(self, path: Path) -> str:
        """Open one file in the same native, closeable bar as agent/channel tabs."""
        from toad.screens.file_preview import FilePreviewScreen

        path = path.expanduser().resolve()
        if mode_name := self._file_preview_modes.get(path):
            if mode_name in self.workspace_sessions.factories:
                await self.select_session(mode_name)
                return mode_name
            # A removed mode must not leave a stale path-to-tab entry.
            del self._file_preview_modes[path]
            self._file_preview_return.pop(mode_name, None)
        self._file_preview_index += 1
        mode_name = f"preview-{self._file_preview_index}"

        def make_screen() -> FilePreviewScreen:
            screen = FilePreviewScreen(path)
            return screen

        self.workspace_sessions.register(mode_name, make_screen)
        self._file_preview_modes[path] = mode_name
        # A new preview belongs beside the tab that opened it. Reusing a file
        # changes focus only, and never shuffles an existing tab unexpectedly.
        self.tab_order.open(mode_name, after=self.selected_mode)
        self.open_tabs_changed.publish(None)
        self.update_show_sessions()
        await self.select_session(mode_name)
        return mode_name

    async def return_from_preview(self, mode_name: str) -> None:
        """Return to the last originating tab, or another still-open view."""
        target = self._file_preview_return.get(mode_name)
        if target is None or target == mode_name or target not in self.workspace_sessions.factories:
            target = self.tab_order.previous(mode_name)
        await self.select_session(target)

    @property
    def open_tabs(self) -> tuple[OpenTab, ...]:
        """All open views, independent of which view is currently selected."""
        snapshot = self._sidebar_snapshot
        presentations = {
            view.thread.name: view.presentation for view in snapshot.threads
        } if snapshot is not None else {}
        tabs: list[OpenTab] = []
        for details in self.session_tracker.ordered_sessions:
            screen = self._main_session_screen(details.mode_name)
            # Identity is maintained by coordination notifications and sidebar
            # snapshot reconciliation. Painting labels must not read the wire.
            name = screen._comms_thread if screen else ""
            presentation = presentations.get(name)
            tabs.append(OpenTab(
                details.mode_name, presentation.label if presentation else details.title or "New Session",
                UnreadPresentation.for_thread(snapshot, name) if snapshot else ExactUnread(),
            ))
        tabs.extend(OpenTab(
            mode, key.title,
            ExactUnread((snapshot.unread if key.kind == "dm" else snapshot.channel_unread).get(key.target, 0))
            if snapshot else ExactUnread(),
        ) for key, mode in self._comms_modes.items())
        tabs.extend(OpenTab(mode, path.name) for path, mode in self._file_preview_modes.items())
        by_mode = {tab.mode_name: tab for tab in tabs}
        return self.tab_order.project(by_mode)

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
        return self.workspace_sessions.selected

    @property
    def selected_mode(self):
        selected = self.selected_session
        return selected.id if self.current_mode == "workspace" and selected is not None else self.current_mode


    @property
    def coordination_wire(self):
        from agent_comms.active_route import resolve_comms_route
        from agent_comms.comms import wire

        # Every access revalidates the route marker; never reuse a cached wire
        # after publication changes the default root.
        selected = resolve_comms_route()
        selected_root = selected.observe_root()
        cached = self._coordination_wire
        if (cached is None or cached.root.resolve() != selected_root
                or self._coordination_route != selected):
            service = wire()
            # Never associate a service from a concurrent route flip with the
            # earlier observation. The next access resolves the route afresh.
            if service.root.resolve() != selected_root or resolve_comms_route() != selected:
                raise ValueError("Comms route changed while opening the service")
            self._coordination_wire = service
            self._coordination_route = selected
            self._sidebar_snapshot = None
        return self._coordination_wire

    def open_wire_export_dialog(self) -> None:
        from toad.widgets.comms_transfer import WireExportDialog

        selected_root = self.coordination_wire.root
        self.push_screen(
            WireExportDialog(selected_root),
            callback=lambda request: self._export_wire(request, selected_root)
            if request is not None else None,
        )

    @work(group="wire-export", exclusive=True, exit_on_error=False)
    async def _export_wire(self, request, selected_root: Path) -> None:
        try:
            if not root_is_current(selected_root):
                raise ValueError("Comms route changed before export")
            comms = self.coordination_wire
            if comms.root.resolve() != selected_root.resolve():
                raise ValueError("Comms route changed before export")
            receipt = await asyncio.to_thread(
                run_selected_write, comms.root, comms.views.export_wire,
                request.destination,
                format=request.format,
                scope=request.scope,
                limit=request.limit, implicit=implicit_root(),
            )
        except Exception as error:
            self.notify(str(error), title="Wire export failed", severity="error")
        else:
            self.notify(
                f"Exported {receipt.exported_messages} messages to {receipt.destination}",
                title="Wire export",
            )

    def open_thread_import_dialog(self) -> None:
        from toad.widgets.comms_transfer import ThreadImportDialog

        selected_root = self.coordination_wire.root
        self.push_screen(
            ThreadImportDialog(),
            callback=lambda request: self._import_thread(request, selected_root)
            if request is not None else None,
        )

    @work(group="thread-import", exclusive=True, exit_on_error=False)
    async def _import_thread(self, request, selected_root: Path) -> None:
        try:
            if not root_is_current(selected_root):
                raise ValueError("Comms route changed before import")
            comms = self.coordination_wire
            if comms.root.resolve() != selected_root.resolve():
                raise ValueError("Comms route changed before import")
            receipt = await asyncio.to_thread(
                run_selected_write, comms.root, comms.threads.import_thread,
                request.source,
                request.format,
                name=request.name,
                session_id=request.session_id,
                worktree=request.worktree, implicit=implicit_root(),
            )
        except Exception as error:
            self.notify(str(error), title="Thread import failed", severity="error")
        else:
            self.thread_actions_changed.publish(None)
            self.notify(
                f"Imported @{receipt.thread} ({receipt.imported_messages} messages) as a stopped thread",
                title="Thread Import",
            )

    async def open_thread_session(
        self,
        *,
        owner_mode: str,
        project_path: Path,
        target: str,
    ) -> str:
        """Open or reuse a resumable wire thread as a tracked agent session."""
        source = self._main_session_screen(owner_mode)
        if source is None:
            from toad.screens.comms import CommsScreen

            owner_view = self.workspace_sessions.views.get(owner_mode)
            if isinstance(owner_view, CommsScreen):
                source = self._main_session_screen(owner_view.owner_mode)
        if source is None:
            return self.selected_mode
        source_identity = source._comms_thread
        source_root = source.coordination_root
        try:
            requested_root = str(current_root())
        except (OSError, ValueError, RuntimeError) as error:
            self.notify(str(error), title="Thread unavailable", severity="error")
            return self.selected_mode
        # A mounted destination already owns its root/thread identity. Focus it
        # before publishing a loading tab or doing route discovery. Unknown
        # aliases and noncanonical roots still use authoritative off-loop reads.
        mounted_root = str(Path(requested_root).expanduser())
        for details in self.session_tracker.ordered_sessions:
            screen = self._main_session_screen(details.mode_name)
            if (
                screen is not None
                and screen.coordination_root == mounted_root
                and screen._comms_thread == target
            ):
                await self.select_session(details.mode_name)
                return details.mode_name
        open_threads = tuple(
            OpenThread(details.mode_name, screen.coordination_root, screen._comms_thread)
            for details in self.session_tracker.ordered_sessions
            if (screen := self._main_session_screen(details.mode_name)) is not None
            and screen.coordination_root is not None
        )
        opening = ThreadOpening(
            owner_mode,
            ThreadNavigationRequest(requested_root, target, project_path, open_threads),
            asyncio.get_running_loop().create_future(),
        )
        if pending := self._thread_openings.get(opening.key):
            return await asyncio.shield(pending.completion)
        self._thread_openings[opening.key] = opening
        return_mode = self.selected_mode
        result = return_mode
        try:
            result = await self._finish_open_thread_session(
                opening.request, owner_mode, project_path, source,
                source_identity, source_root, return_mode,
            )
            return result
        finally:
            self._thread_openings.pop(opening.key)
            if not opening.completion.done():
                opening.completion.set_result(result)

    async def _finish_open_thread_session(
        self,
        request: ThreadNavigationRequest,
        owner_mode: str,
        project_path: Path,
        source: "MainScreen",
        source_identity: str,
        source_root: str | None,
        return_mode: str,
    ) -> str:
        from toad.screens.main import MainScreen

        try:
            prepared = await self.navigation_reader.read(
                request
            )
        except Exception as error:
            self.notify(str(error), title="Thread unavailable", severity="error")
            return self.selected_mode
        if (
            prepared is None
            or self.selected_mode != return_mode
            or not source.is_attached
            or owner_mode not in self.workspace_sessions.factories
            or source._comms_thread != source_identity
            or source.coordination_root != source_root
            or not root_is_current(request.root)
        ):
            return self.selected_mode
        coordination_root, thread = prepared.root, prepared.thread
        if not prepared.active:
            self.notify(
                f"@{thread.name} is stopped; choose Start thread to resume it",
                title="Thread view",
            )
            return await self.open_comms_session(
                owner_mode=owner_mode, project_path=project_path,
                me=source._comms_thread, target=DirectTarget(thread.name),
            )
        if existing := prepared.existing:
            screen = self._main_session_screen(existing.mode)
            if (
                screen is not None
                and screen.coordination_root == existing.root
                and screen._comms_thread == existing.name
            ):
                await self.select_session(existing.mode)
                return existing.mode
            # A view changed identity during discovery; don't create a duplicate
            # using an obsolete snapshot of the available open threads.
            return self.selected_mode

        if not prepared.resumable:
            source = self._main_session_screen(owner_mode)
            if source is None:
                return owner_mode
            me = source._comms_thread
            if thread.name == me:
                await self.select_session(owner_mode)
                return owner_mode
            return await self.open_comms_session(
                owner_mode=owner_mode,
                project_path=project_path,
                me=me,
                target=DirectTarget(thread.name),

            )

        if source._agent is None:
            self.notify(
                "The owning agent session is unavailable",
                title="Thread unavailable",
                severity="error",
            )
            return owner_mode

        def get_screen() -> MainScreen:
            screen = MainScreen(
                prepared.project,
                source._agent,
                agent_session_id=thread.name,
                agent_session_title=thread.name,
            )
            screen.initial_coordination_root = coordination_root
            screen._comms_thread = thread.name
            screen.set_reactive(MainScreen.column, self.column)
            screen.set_reactive(MainScreen.column_width, self.column_width)
            screen.set_reactive(MainScreen.scrollbar, self.scrollbar)
            screen.watch(
                self,
                "column",
                lambda value: setattr(screen, "column", value),
                init=False,
            )
            screen.watch(
                self,
                "column_width",
                lambda value: setattr(screen, "column_width", value),
                init=False,
            )
            screen.watch(
                self,
                "scrollbar",
                lambda value: setattr(screen, "scrollbar", value),
                init=False,
            )
            return screen

        details = await self.new_session_screen(get_screen, title=thread.name)
        if screen := self._main_session_screen(details.mode_name):
            await screen.wait_content_ready()
        return details.mode_name if self.workspace_sessions.views.get(details.mode_name) else self.selected_mode

    def sync_coordination_identity(
        self, owner_mode: str, previous: str, current: str
    ) -> None:
        """Move open communication views to a renamed canonical thread."""
        from agent_comms.comms import wire

        from toad.screens.comms import CommsScreen
        from toad.widgets.comms_chat import CommsChatView
        from toad.widgets.comms_sidebar import CommsSidebar, CoordinationStatus
        from toad.widgets.recovery_view import RecoveryView

        for key, mode_name in list(self._comms_modes.items()):
            if key.owner_mode != owner_mode:
                continue
            if key.me != previous and wire(key.root).registry.canonical_name(key.me) != current:
                continue
            del self._comms_modes[key]
            self._comms_modes[replace(key, me=current)] = mode_name
            try:
                screen = self.workspace_sessions.require(mode_name)
            except KeyError, IndexError:
                continue
            if not isinstance(screen, CommsScreen):
                continue
            screen.me = current
            if chat := screen.query_one_optional(CommsChatView):
                chat._me = current
            if sidebar := screen.query_one_optional(CommsSidebar):
                sidebar.session_thread = current
            status = screen.query_one_optional(CoordinationStatus)
            if status is not None:
                status.set_thread(current)
            if recovery := screen.query_one_optional(RecoveryView):
                recovery.set_identity(current, screen.recovery_root)

    def sync_recovery_root(self, owner_mode: str, trusted_root: str | None) -> None:
        """Rebind already-open channel tabs only to their ACP owner's wire."""
        from toad.screens.comms import CommsScreen
        from toad.widgets.recovery_view import RecoveryView

        for key, mode_name in self._comms_modes.items():
            if key.owner_mode != owner_mode:
                continue
            try:
                screen = self.workspace_sessions.require(mode_name)
            except (KeyError, IndexError):
                continue
            if not isinstance(screen, CommsScreen):
                continue
            root = (
                trusted_root if trusted_root is not None
                and Path(trusted_root).expanduser().resolve() == Path(key.root) else None
            )
            screen.recovery_root = root
            if recovery := screen.query_one_optional(RecoveryView):
                recovery.set_identity(screen.me, root)

    def local_coordination_threads(self) -> set[str]:
        """Authoritative wire identities already represented by local sessions."""
        threads: set[str] = set()
        for details in self.session_tracker.ordered_sessions:
            screen = self._main_session_screen(details.mode_name)
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
            sidebar._wire.root
            if sidebar is not None and sidebar._wire is not None
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
        if any(history.is_attached and (history.has_newer or history._loading)
               for history in window.histories):
            return
        try:
            comms = self.coordination_wire
            await asyncio.to_thread(
                run_selected_write, comms.root, comms.views.mark_thread_view_read,
                screen._session_thread, worktree=str(self.project_dir),
                through=through, implicit=implicit_root(),
            )
        except (OSError, ValueError):
            # Source replacement or deletion is resolved by the next snapshot.
            return

    def invoke_thread_action(
        self, action: ThreadAction, subject: str, actor: str, session_modes: tuple[str, ...] = ()
    ) -> None:
        """Track one UI request per thread while the core operation runs off-loop."""
        screen = self.screen
        source_root = screen.coordination_root
        if source_root is None:
            from toad.widgets.comms_sidebar import CommsSidebar

            sidebar = screen.query_one_optional(CommsSidebar)
            if sidebar is not None and sidebar._wire is not None:
                source_root = sidebar._wire.root
        if source_root is not None and not root_is_current(source_root):
            self.notify("Comms route changed; reopen this view", title="Session action", severity="error")
            return
        try:
            selected_root = str(current_root())
        except (OSError, ValueError, RuntimeError) as error:
            self.notify(str(error), title="Session action", severity="error")
            return
        if subject in self.pending_thread_actions:
            self.notify(f"An action for @{subject} is already in progress", title="Session action")
            return
        self.pending_thread_actions[subject] = action.pending
        self.thread_actions_changed.publish(None)
        self._run_thread_action(action, subject, actor, session_modes, selected_root)

    @work(group="thread-actions")
    async def _run_thread_action(
        self, action: ThreadAction, subject: str, actor: str, session_modes: tuple[str, ...],
        selected_root: str,
    ) -> None:
        try:
            if not root_is_current(selected_root):
                raise ValueError("Comms route changed before the thread action")
            comms = self.coordination_wire
            if comms.root.resolve() != Path(selected_root):
                raise ValueError("Comms route changed before the thread action")
            ctx = ThreadActionContext(comms, subject, actor, self.project_dir, session_modes)
            result = await asyncio.to_thread(
                run_selected_write, comms.root, action.apply, ctx, implicit=implicit_root(),
            )
            await action.completed(self, ctx, result)
        except Exception as error:
            self.notify(str(error), title=f"Session action: {subject}", severity="error")
        finally:
            self.pending_thread_actions.pop(subject, None)
            self.thread_actions_changed.publish(None)

    def sync_coordination_project(self, owner_mode: str, project: Path) -> None:
        """Keep channel/DM views attached to a session on its current project."""
        from toad.screens.comms import CommsScreen
        from toad.widgets.comms_chat import CommsChatView

        for key, mode_name in self._comms_modes.items():
            if key.owner_mode != owner_mode:
                continue
            try:
                screen = self.workspace_sessions.require(mode_name)
            except KeyError, IndexError:
                continue
            if isinstance(screen, CommsScreen):
                screen.project_path = project
                if chat := screen.query_one_optional(CommsChatView):
                    chat.project_path = project
                    chat.working_directory = str(project)

    async def close_session_mode(self, mode_name: str) -> None:
        """Close any tracked mode after first switching to a safe mode."""
        if path := next((path for path, mode in self._file_preview_modes.items()
                         if mode == mode_name), None):
            if self.selected_mode == mode_name:
                await self.return_from_preview(mode_name)
            del self._file_preview_modes[path]
            self._file_preview_return.pop(mode_name, None)
            self.tab_order.close({mode_name})
            self.open_tabs_changed.publish(None)
            self.update_show_sessions()
            await self.workspace_sessions.close(mode_name)
            return
        session_tracker = self.session_tracker
        if session_tracker.get_session(mode_name) is None:
            comms_key = next(
                (
                    key
                    for key, comms_mode in self._comms_modes.items()
                    if comms_mode == mode_name
                ),
                None,
            )
            if comms_key is not None:
                owner_mode = comms_key.owner_mode
                if self.selected_mode == mode_name:
                    if session_tracker.get_session(owner_mode) is not None:
                        await self.select_session(owner_mode)
                    else:
                        await self.select_session("store")
                del self._comms_modes[comms_key]
                self.tab_order.close({mode_name})
                self.open_tabs_changed.publish(None)
                self.update_show_sessions()
                await self.workspace_sessions.close(mode_name)
            return

        closing_modes = {mode_name}
        for key, comms_mode in self._comms_modes.items():
            if key.owner_mode == mode_name:
                closing_modes.add(comms_mode)

        remaining_modes = [
            details.mode_name
            for details in session_tracker.ordered_sessions
            if details.mode_name not in closing_modes
        ]
        closing_main = self._main_session_screen(mode_name)
        if self.selected_mode not in closing_modes:
            pass
        elif not remaining_modes:
            if closing_main is not None and closing_main._agent is not None:
                from toad.screens.main import MainScreen

                def get_replacement_screen() -> MainScreen:
                    return MainScreen(
                        closing_main.project_path,
                        closing_main._agent,
                    ).data_bind(
                        column=ToadApp.column,
                        column_width=ToadApp.column_width,
                        scrollbar=ToadApp.scrollbar,
                    )

                await self.new_session_screen(get_replacement_screen)
            else:
                await self.select_session("store")
        else:
            next_mode = self.tab_order.previous(
                mode_name, eligible=remaining_modes, excluded=closing_modes
            )
            await self.select_session(next_mode)

        for closing_mode in closing_modes:
            session_tracker.close_session(closing_mode)
        for key, comms_mode in list(self._comms_modes.items()):
            if comms_mode in closing_modes:
                del self._comms_modes[key]
        self.tab_order.close(closing_modes)
        self.open_tabs_changed.publish(None)
        self.update_show_sessions()
        # Teardown of a large hidden transcript can await many widget exits.
        # The selected remaining tab and its closeable bar already reflect the
        # user's action while those screens finish ordinary removal.
        for closing_mode in closing_modes:
            await self.workspace_sessions.close(closing_mode)

    async def on_mount(self) -> None:
        self.capture_event("toad-run")
        self.anon_id  # Created on frst reference
        if mode := self._initial_mode:
            self.select_session(mode)
        else:
            await self.new_session_screen(self.get_main_screen)

        self.terminal_attention.attach()
        self.set_timer(1, self.run_version_check)
        self.set_process_title()
        self.update_show_sessions()

    @work(thread=True, exit_on_error=False)
    def set_process_title(self) -> None:
        try:
            import setproctitle

            setproctitle.setproctitle("toad")
        except Exception:
            pass

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
            if isinstance(action, str) and action.startswith("link(") and action.endswith(")"):
                try:
                    href = ast.literal_eval(action[5:-1])
                except SyntaxError, ValueError:
                    href = None
                path = None
                if isinstance(href, str) and href.startswith("toad-file:"):
                    path = Path(href.removeprefix("toad-file:")).expanduser().resolve()
                elif isinstance(href, str) and href.startswith("toad-file-search:"):
                    from urllib.parse import unquote

                    from toad.conversation_markdown import _file_lookup_notice, _unique_project_file

                    name = unquote(href.removeprefix("toad-file-search:"))
                    root = Path(default_namespace.screen.project_path)
                    path, status = await asyncio.to_thread(_unique_project_file, root, name)
                    if path is None:
                        event.stop()
                        self.notify(_file_lookup_notice(name, root, status),
                                    title="File preview", severity="warning")
                        return True
                if path is not None:
                    from toad.widgets.comms_menu import show_target_menu

                    full_path = str(path)
                    event.stop()
                    event.prevent_default()
                    show_target_menu(
                        self.screen, event.screen_offset, full_path,
                        [("copy_path", "Copy full path")],
                        {"copy_path": lambda: self.copy_to_clipboard(full_path)},
                    )
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

    def run_on_exit(self):
        if self.update_required and self.version_meta is not None:
            version_meta = self.version_meta
            from rich.console import Console
            from rich.panel import Panel

            console = Console()
            console.print(
                Panel(
                    version_meta.upgrade_message,
                    style="magenta",
                    border_style="dim green",
                    title="🐸 [bold green not dim]Update available![/] 🐸",
                    expand=False,
                    padding=(1, 2),
                )
            )
            console.print(f"Please visit {version_meta.visit_url}")

    @work(exit_on_error=False)
    async def run_version_check(self) -> None:
        """Check remote version."""
        from toad.version import VersionCheckFailed, check_version

        try:
            update_required, version_meta = await check_version()
        except VersionCheckFailed:
            return
        self.version_meta = version_meta
        self.update_required = update_required

    def get_main_screen(self) -> MainScreen:
        """Make the default screen.

        Returns:
            Instance of `MainScreen`
        """
        # Lazy import
        from toad.screens.main import MainScreen

        project_path = Path(self.project_dir or "./").resolve().absolute()
        session_id = self._initial_agent_session_id
        self._initial_agent_session_id = None
        return MainScreen(
            project_path,
            self.agent_data,
            agent_session_id=session_id,
            agent_session_title=session_id,
        ).data_bind(
            column=ToadApp.column,
            column_width=ToadApp.column_width,
            scrollbar=ToadApp.scrollbar,
        )

    @work
    async def action_settings(self) -> None:
        await self.push_screen_wait("settings")
        await self.save_settings()

    async def action_set_footer(self, visible: bool) -> None:
        """Persist footer visibility from the command palette."""
        self.settings.ui.footer = visible
        await self.save_settings()
        self.notify(
            "Footer shortcut bar shown" if visible else "Footer shortcut bar hidden",
            title="Interface",
        )

    async def action_quit(self) -> None:
        """An [action](/guide/actions) to quit the app as soon as possible."""

        self.screen.set_focus(None)

        async def save_settings_and_exit():
            await self.save_settings()
            self.exit()

        # TODO: Can we avoid the timer?
        # If the user presses ctrl+q while on the settings page, we want to make sure the blur event is handled,
        # which will update the setting the user is editing.
        self.set_timer(0.05, save_settings_and_exit)

    def action_help_quit(self) -> None:
        if (time := monotonic()) - self.last_ctrl_c_time <= 5.0:
            self.exit()
        self.last_ctrl_c_time = time
        self.notify(
            "Press [b]ctrl+c[/b] again to quit the app", title="Do you want to quit?"
        )

    def action_toggle_help_panel(self):
        if self.screen.query("HelpPanel"):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    def update_show_sessions(self) -> None:
        self.show_sessions = self.settings.ui.sessions_bar.shown(len(self.open_tabs))

    @on(messages.SessionNavigate)
    def on_session_navigate(self, event: messages.SessionNavigate) -> None:
        modes = [tab.mode_name for tab in self.open_tabs]
        if self.selected_mode in modes:
            self.select_session(modes[(modes.index(self.selected_mode) + event.direction) % len(modes)])

    @on(messages.SessionSwitch)
    def on_session_switch(self, event: messages.SessionSwitch) -> None:
        self.select_session(event.mode_name)

    @on(messages.SessionNew)
    def on_session_new(self, event: messages.SessionNew) -> None:
        self.launch_agent(
            event.agent, project_path=Path(event.path), initial_prompt=event.prompt
        )

    @on(messages.SessionCreate)
    async def on_session_create(self, event: messages.SessionCreate) -> None:
        source = self._main_session_screen(event.source_mode)
        if source is None:
            try:
                from toad.screens.comms import CommsScreen

                screen = self.workspace_sessions.require(event.source_mode)
                if isinstance(screen, CommsScreen):
                    source = self._main_session_screen(screen.owner_mode)
            except KeyError, IndexError:
                pass
        if source is not None and source._agent is not None:
            from toad.screens.main import MainScreen

            def get_screen() -> MainScreen:
                return MainScreen(source.project_path, source._agent).data_bind(
                    column=ToadApp.column,
                    column_width=ToadApp.column_width,
                    scrollbar=ToadApp.scrollbar,
                )

            await self.new_session_screen(get_screen)
        else:
            await self.new_session_screen(self.get_main_screen)

    def _main_session_screen(self, mode_name: str) -> "MainScreen | None":
        from toad.screens.main import MainScreen

        try:
            view = self.workspace_sessions.require(mode_name)
        except KeyError, IndexError:
            return None
        return view if isinstance(view, MainScreen) else None

    @on(messages.SessionRename)
    async def on_session_rename(self, event: messages.SessionRename) -> None:
        name = event.name.strip()
        screen = self._main_session_screen(event.mode_name)
        if not name or screen is None:
            return
        await screen.conversation.rename_session(name)

    @on(messages.SessionArchive)
    async def on_session_archive(self, event: messages.SessionArchive) -> None:
        await self.close_session_mode(event.mode_name)

    @on(messages.SessionClose)
    def on_session_close(self) -> None:
        self.update_show_sessions()

    @work
    async def action_sessions(self) -> None:
        from toad.widgets.comms_sidebar import CommsSidebar
        from toad.widgets.side_bar import SideBar, SideBarCollapsible

        sidebar = self.screen.query_one_optional(CommsSidebar)
        if sidebar is None:
            sessions = self.session_tracker.ordered_sessions
            if not sessions:
                self.notify("No sessions are open", title="Sessions")
                return
            await self.select_session(sessions[-1].mode_name)
            sidebar = self.screen.query_one_optional(CommsSidebar)
        if sidebar is None:
            return
        sidebar.query_ancestor(SideBar).reveal()
        sidebar.query_ancestor(SideBarCollapsible).collapsed = False
        await sidebar.focus_current_session()

    @on(messages.LaunchAgent)
    def on_launch_agent(self, message: messages.LaunchAgent) -> None:
        self.launch_agent(
            message.identity,
            agent_session_id=message.session_id,
            session_pk=message.pk,
            initial_prompt=message.prompt,
        )

    @work
    async def launch_agent(
        self,
        agent_identity: str,
        *,
        agent_session_id: str | None = None,
        session_pk: int | None = None,
        project_path: Path | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        from toad.agent_schema import Agent
        from toad.agents import read_agents
        from toad.screens.main import MainScreen

        agent: Agent | None = None
        session_title: str | None = None
        if session_pk is not None:
            db = DB()
            session = await db.session_get(session_pk)
            if session is not None:
                session_title = session.title
                if agent_data := session.meta_json.agent_data:
                    agent = agent_data

        if agent is None:
            agents = await read_agents()
            try:
                agent = agents[agent_identity]
            except KeyError:
                self.notify("Agent not found", title="Launch agent", severity="error")
                return
        if project_path is None:
            project_path = Path(self.project_dir or os.getcwd())

        if agent_session_id is not None:
            for details in self.session_tracker.ordered_sessions:
                existing = self._main_session_screen(details.mode_name)
                if existing is None or existing._agent is None:
                    continue
                if existing._agent["identity"] != agent_identity:
                    continue
                live_agent = existing.conversation.agent
                session_ids = {
                    existing._agent_session_id,
                    live_agent.session_id if live_agent is not None else None,
                }
                matches = agent_session_id in session_ids
                if existing.coordination_root is not None:
                    from agent_comms.comms import wire

                    comms = wire(existing.coordination_root)
                    matches = matches or (
                        comms.registry.canonical_name(agent_session_id)
                        == existing._session_thread
                    )
                if matches:
                    await self.select_session(details.mode_name)
                    return

        def get_screen():
            screen = MainScreen(
                project_path,
                agent,
                agent_session_id,
                agent_session_title=session_title,
                session_pk=session_pk,
                initial_prompt=initial_prompt,
            ).data_bind(
                column=ToadApp.column,
                column_width=ToadApp.column_width,
            )

            return screen

        await self.new_session_screen(get_screen)
