import asyncio
import ast
from dataclasses import replace
from importlib.resources import files
from datetime import datetime, timezone
from functools import cached_property, partial
import os
from pathlib import Path
import platform
import json
from time import monotonic
from typing import Any, Callable, ClassVar, TYPE_CHECKING

from rich import terminal_theme

from textual import on, work
from textual.binding import Binding, BindingType
from textual.content import Content
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.reactive import var, reactive
from textual.app import App
from textual import events
from textual.signal import Signal
from textual.timer import Timer
from textual.notifications import Notify
from textual.screen import Screen
from textual.await_complete import AwaitComplete

import toad
from toad.db import DB
from toad.settings import Schema, Settings
from toad.agent_schema import Agent as AgentData
from toad import messages
from toad.settings_schema import SCHEMA
from toad.version import VersionMeta
from toad import paths
from toad import atomic
from toad.render_backend import Renderer, create_renderer
from toad.session_tracker import SessionTracker, SessionDetails, OpenTab, CommsViewKey, SidebarState

if TYPE_CHECKING:
    from toad.screens.main import MainScreen
    from toad.screens.settings import SettingsScreen
    from toad.screens.store import StoreScreen
    from toad.db import DB


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
        visible = app.settings.get("ui.footer", bool)
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


def get_store_screen() -> StoreScreen:
    """Get the store screen (lazily loaded)."""
    from toad.screens.store import StoreScreen

    return StoreScreen()


class ToadApp(App, inherit_bindings=False):
    """The top level app."""

    CSS_PATH = ["toad.tcss", "screens/comms.tcss"]
    SCREENS = {
        "settings": get_settings_screen,
    }
    COMMANDS = {InterfaceProvider}
    MODES = {"store": get_store_screen}
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

    _settings = var(dict)
    column: reactive[bool] = reactive(False)
    column_width: reactive[int] = reactive(100)
    scrollbar: reactive[str] = reactive("normal")
    last_ctrl_c_time = reactive(0.0)
    update_required: reactive[bool] = reactive(False)
    terminal_title: var[str] = var("Toad")
    terminal_title_icon: var[str] = var("🐸")
    terminal_title_flash = var(0)
    terminal_title_blink = var(False)
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
        self.render_processes: Renderer = create_renderer() if renderer is None else renderer
        self.settings_changed_signal: Signal[tuple[int, object]] = Signal(
            self, "settings_changed"
        )
        self.agent_data = agent_data

        self._initial_mode = mode
        self._initial_agent_session_id = agent_session_id
        self.version_meta: VersionMeta | None = None
        self._supports_pyperclip: bool | None = None
        self._terminal_title_flash_timer: Timer | None = None

        self.session_update_signal: Signal[tuple[str, SessionDetails | None]] = Signal(
            self, "session_update"
        )
        self._session_tracker = SessionTracker(self.session_update_signal)
        self._comms_modes: dict[CommsViewKey, str] = {}
        self._file_preview_modes: dict[Path, str] = {}
        self._file_preview_return: dict[str, str] = {}
        self._file_preview_index = 0
        self._open_tab_order: list[str] = []
        self._tab_history: list[str] = []
        self._tab_history_index = -1
        self._sidebar_snapshot = None
        self.pending_thread_actions: dict[str, str] = {}
        self.thread_actions_changed: Signal[None] = Signal(self, "thread-actions-changed")
        self.sidebar_state = SidebarState()
        self._mode_switch_lock = asyncio.Lock()
        self._atomic_mode_switch = False
        self._pending_mode_switch: str | None = None
        self.open_tabs_changed: Signal[None] = Signal(self, "open-tabs-changed")
        self.tab_history_changed: Signal[None] = Signal(self, "tab-history-changed")
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
        await self.render_processes.aclose()

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
    def settings_schema(self) -> Schema:
        return Schema(SCHEMA)

    @cached_property
    def version(self) -> str:
        """Version of the app."""
        from toad import get_version

        return get_version()

    @cached_property
    def settings(self) -> Settings:
        """App settings"""
        return Settings(
            self.settings_schema, self._settings, on_set_callback=self.setting_updated
        )

    @cached_property
    def anon_id(self) -> str:
        """An anonymous ID for usage collection."""
        if not (anon_id := self.settings.get("anon_id", str, expand=False)):
            # Create a random UUID on demand
            import uuid

            anon_id = str(uuid.uuid4())
            self.settings.set("anon_id", anon_id)
            self._save_settings()
            self.call_later(self.capture_event, "toad-install")
        return anon_id

    @property
    def session_tracker(self) -> SessionTracker:
        return self._session_tracker

    def copy_to_clipboard(self, text: str) -> None:
        """Override copy to clipboard to use pyperclip first, then OSC 52.

        Args:
            text: Text to copy.
        """
        if self._supports_pyperclip is None:
            try:
                import pyperclip
            except ImportError:
                self._supports_pyperclip = False
            else:
                self._supports_pyperclip = True

        if self._supports_pyperclip:
            import pyperclip

            try:
                pyperclip.copy(text)
            except Exception:
                pass
            else:
                # OSC 52 is a fallback, not a second copy operation. Some
                # terminals truncate long escape strings and would overwrite
                # the complete native clipboard with only a short prefix.
                self._clipboard = text
                return
        super().copy_to_clipboard(text)

    def update_terminal_title(self) -> None:
        """Update the terminal title."""
        screen_title = self.screen.title

        title = (
            f"{self.terminal_title} — {screen_title}"
            if screen_title
            else self.terminal_title
        )
        icon = self.terminal_title_icon
        blink = self.terminal_title_blink

        if self.terminal_title_flash:
            if blink:
                terminal_title = f"{icon} {title}"
            else:
                terminal_title = f"👉 {title}" if title else icon
        else:
            terminal_title = f"{icon} {title}"

        if driver := self._driver:
            driver.write(f"\033]0;{terminal_title}\007")

    def watch_terminal_title_blink(self) -> None:
        self.update_terminal_title()

    def watch_terminal_title_flash(self, terminal_title_flash: int) -> None:

        if not self.settings.get("notifications.blink_title", bool):
            # Ignore if blink title is disabled
            return

        def toggle_blink() -> None:
            self.terminal_title_blink = not self.terminal_title_blink

        if terminal_title_flash:
            if self._terminal_title_flash_timer is None:
                self._terminal_title_flash_timer = self.set_interval(0.5, toggle_blink)
        else:
            if self._terminal_title_flash_timer is not None:
                self._terminal_title_flash_timer.stop()
                self.terminal_title_blink = False
                self._terminal_title_flash_timer = None
        self.update_terminal_title()

    def watch_terminal_title(self, title: str) -> None:
        self.update_terminal_title()

    def terminal_alert(self, flash: bool = True) -> None:
        if flash:
            self.terminal_title_flash += 1
        else:
            self.terminal_title_flash -= 1

    @cached_property
    def term_program(self) -> str:
        """An identifier for the terminal software."""
        if term_program := os.environ.get("TERM_PROGRAM"):
            return term_program

        # Windows Terminal
        if "WT_SESSION" in os.environ:
            return "Windows Terminal"

        # Kitty
        if "KITTY_WINDOW_ID" in os.environ:
            return "Kitty"

        # Alacritty
        if "ALACRITTY_SOCKET" in os.environ or "ALACRITTY_LOG" in os.environ:
            return "Alacritty"

        # VTE-based terminals (GNOME Terminal, Tilix, etc.)
        if "VTE_VERSION" in os.environ:
            return "VTE-based (GNOME Terminal/Tilix/etc.)"

        # Konsole
        if "KONSOLE_VERSION" in os.environ:
            return "Konsole"

        return "Unknown"

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
            "term_program": self.term_program,
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
        if not self.settings.get("statistics.allow_collect", bool):
            # User has disabled stats
            return

        import httpx

        try:
            async with httpx.AsyncClient() as client:
                await client.post(POSTHOG_EVENT_URL, json=body_json)
        except Exception:
            pass

    @work(thread=True, exit_on_error=False)
    def system_notify(
        self, message: str, *, title: str = "", sound: str | None = None
    ) -> None:
        """Use OS level notifications.

        Args:
            message: Message to display.
            title: Title of the notificaiton.
            sound: filename (minus .wav) of a sound effect in the sounds/ directory.
        """
        system_notifications = self.settings.get("notifications.system", str)
        if not (
            system_notifications == "always"
            or (system_notifications == "blur" and not self.app_focus)
        ):
            return

        from notifypy import Notify

        notification = Notify()
        notification.message = message
        notification.title = title
        notification.application_name = "🐸 Toad" if toad.os == "macos" else "Toad"
        if sound and self.settings.get("notifications.enable_sounds", bool):
            sound_path = str(files("toad.data").joinpath(f"sounds/{sound}.wav"))
            notification.audio = sound_path

        icon_path = str(files("toad.data").joinpath("images/frog.png"))
        notification.icon = icon_path

        notification.send()

    def on_notify(self, event: Notify) -> None:
        """Handle notification message."""
        system_notifications = self.settings.get("notifications.system", str)
        if system_notifications == "always" or (
            system_notifications == "blur" and not self.app_focus
        ):
            hide_low_severity = self.settings.get(
                "notifications.hide_low_severity", bool
            )
            if event.notification.markup:
                # Strip content markup
                message = Content.from_markup(event.notification.message).plain
            else:
                message = event.notification.message
            if not (hide_low_severity and event.notification.severity == "information"):
                self.system_notify(message, title=event.notification.title)
        self._notifications.add(event.notification)
        self._refresh_notifications()

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

    def setting_updated(self, key: str, value: object) -> None:
        if key == "ui.column":
            if isinstance(value, bool):
                self.column = value
        elif key == "ui.column-width":
            if isinstance(value, int):
                self.column_width = value
        elif key == "ui.theme":
            if isinstance(value, str):
                self.theme = value
        elif key == "ui.scrollbar":
            if isinstance(value, str):
                self.scrollbar = value
        elif key == "ui.compact-input":
            self.set_class(bool(value), "-compact-input")
        elif key == "ui.footer":
            self.set_class(not bool(value), "-hide-footer")
        elif key == "ui.status-line":
            self.set_class(not bool(value), "-hide-status-line")
        elif key == "ui.agent-title":
            self.set_class(not bool(value), "-hide-agent-title")
        elif key == "ui.info-bar":
            self.set_class(not bool(value), "-hide-info-bar")
        elif key == "agent.thoughts":
            self.set_class(not bool(value), "-hide-thoughts")
        elif key == "ui.sessions-bar":
            self.update_show_sessions()

        self.settings_changed_signal.publish((key, value))

    async def on_load(self) -> None:
        self._prewarm_conversation_css()
        db = await self.get_db()
        await db.create()
        settings_path = self.settings_path
        if settings_path.exists():
            settings = json.loads(settings_path.read_text("utf-8"))
        else:
            settings = {}
            settings_path.write_text(
                json.dumps(settings, indent=4, separators=(", ", ": ")), "utf-8"
            )
            self.notify(f"Wrote default settings to {settings_path}", title="Settings")
        self.ansi_theme_dark = DRACULA_TERMINAL_THEME
        self._settings = settings
        self.settings.set_all()

    def _prewarm_conversation_css(self) -> None:
        """Load known conversation classes' default CSS in one parse.

        The classes are discovered through their ordinary inheritance rather
        than maintaining a manual list of every channel, tool and Markdown
        component. Registration deduplicates identical sources when widgets
        eventually mount, avoiding a full CSS rebuild of already-open tabs.
        """
        from textual.widget import Widget
        from textual.widgets.markdown import Markdown
        from textual.widgets._footer import KeyGroup

        from toad.screens import main, comms  # noqa: F401 - register widget classes
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
                        or widget_type in markdown_blocks or widget_type is KeyGroup):
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
        self, get_screen: Callable[[], Screen]
    ) -> SessionDetails:
        session_details = self._session_tracker.new_session()
        self._open_tab_order.append(session_details.mode_name)
        self.update_show_sessions()
        self.session_update_signal.publish((session_details.mode_name, session_details))

        def make_screen() -> Screen:
            screen = get_screen()
            screen.id = session_details.mode_name
            return screen

        self.add_mode(session_details.mode_name, make_screen)
        await self.switch_mode(session_details.mode_name)
        return session_details

    def switch_mode(self, mode: str, *, history_index: int | None = None) -> AwaitComplete:
        from toad.screens.session_view import SessionView

        if mode in self._file_preview_modes.values() and mode != self.current_mode:
            self._file_preview_return[mode] = self.current_mode
        if self.is_running and mode != self.current_mode:
            # A direct tab/sidebar click has declared its destination, but
            # AwaitComplete schedules the serialized transition for the next
            # event-loop turn. Do not let the departing screen's older queued
            # full-layout timer outrun that explicit navigation request.
            self._pending_mode_switch = mode
        # Capture before the transition starts. ScreenSuspend is queued and can
        # otherwise arrive after the destination has already restored its view.
        if self.is_running:
            for screen in reversed(self.screen_stack):
                if isinstance(screen, SessionView):
                    screen.capture_navigation()
                    break
        return AwaitComplete(self._switch_mode_ready(mode, history_index=history_index))

    def _tab_history_target(self, direction: int) -> tuple[int, str] | None:
        """The next still-open view in the user's visited-tab history."""
        valid = set(self._open_tab_order)
        index = self._tab_history_index + direction
        while 0 <= index < len(self._tab_history):
            mode = self._tab_history[index]
            if mode in valid and mode in self._screen_stacks:
                return index, mode
            index += direction
        return None

    def can_navigate_tab_history(self, direction: int) -> bool:
        return self._tab_history_target(direction) is not None

    def navigate_tab_history(self, direction: int) -> None:
        if target := self._tab_history_target(direction):
            index, mode = target
            self.switch_mode(mode, history_index=index)

    def _record_tab_visit(self, mode: str, history_index: int | None) -> None:
        if mode not in self._open_tab_order:
            return
        if (history_index is not None and 0 <= history_index < len(self._tab_history)
                and self._tab_history[history_index] == mode):
            self._tab_history_index = history_index
        else:
            del self._tab_history[self._tab_history_index + 1:]
            self._tab_history.append(mode)
            self._tab_history_index = len(self._tab_history) - 1
        self.tab_history_changed.publish(None)

    def _prune_tab_history(self) -> None:
        """Closing a tab removes every visit to it without changing live tabs."""
        valid = set(self._open_tab_order)
        retained = []
        cursor = -1
        for index, mode in enumerate(self._tab_history):
            if mode in valid:
                retained.append(mode)
                if index <= self._tab_history_index:
                    cursor = len(retained) - 1
        if retained != self._tab_history:
            self._tab_history, self._tab_history_index = retained, cursor
            self.tab_history_changed.publish(None)

    def delay_update(self, delay: float = 0.05) -> None:
        # Textual's switch_mode uses a timed repaint mask. This application
        # already holds a render transaction until the destination is complete.
        if not self._atomic_mode_switch:
            super().delay_update(delay)

    def _display(self, screen: Screen, renderable) -> None:
        from toad.screens.comms import CommsScreen

        super()._display(screen, renderable)
        if (renderable is not None and not self._batch_count and screen is self.screen
                and isinstance(screen, CommsScreen)):
            # call_after_refresh may run on an unpainted update. A real Linux
            # terminal writes asynchronously: do not start expensive native
            # composition until the opening frame has actually been flushed.
            after_flush = getattr(self._driver, "call_after_flush", None)
            if (after_flush is not None and not self.is_headless
                    and not screen._flush_queued and not screen._content_loaded):
                screen._flush_queued = True
                loop = asyncio.get_running_loop()

                def release_hydration() -> None:
                    try:
                        loop.call_soon_threadsafe(screen._start_hydration)
                    except RuntimeError:
                        pass  # The app closed after this terminal write.

                after_flush(release_hydration)
            elif after_flush is None or self.is_headless:
                screen._start_hydration()

    def _load_screen_css(self, screen: Screen) -> None:
        from toad.screens.session_view import SessionView

        super()._load_screen_css(screen)
        if isinstance(screen, SessionView) and not screen.is_mounted:
            # Registration applies current styles to each newly mounted child.
            # Mark this fresh root current too, avoiding Textual's two complete
            # stylesheet reparses while initializing a new screen-stack mode.
            self.stylesheet.apply(screen)
            screen._css_update_count = self._css_update_count

    async def _switch_mode_ready(self, mode: str, *, history_index: int | None = None) -> None:
        from toad.screens.comms import CommsScreen
        from toad.screens.session_view import SessionView

        try:
            async with self._mode_switch_lock:
                previous_mode = self.current_mode
                with self.batch_update():
                    self._atomic_mode_switch = True
                    try:
                        mounted = super().switch_mode(mode)
                    finally:
                        self._atomic_mode_switch = False
                    await mounted
                    screen = self.screen
                    if isinstance(screen, SessionView):
                        await screen.prepare_navigation()
                        await screen.layout_navigation()
                if (isinstance(screen, CommsScreen) and screen.is_current
                        and not screen._content_loaded):
                    # The three-widget opening screen was measured inside the
                    # atomic switch, but that paint was suppressed by the
                    # batch. Commit it now rather than waiting another update
                    # timer tick before hydration is allowed to begin.
                    screen._dirty_widgets.add(screen)
                    screen._refresh_layout(self.size)
                if mode != previous_mode:
                    self._record_tab_visit(mode, history_index)
        finally:
            if self._pending_mode_switch == mode:
                self._pending_mode_switch = None
                if self.is_running and self._screen_stacks.get(self.current_mode):
                    self.screen.check_idle()

    async def open_comms_session(
        self,
        *,
        owner_mode: str,
        project_path: Path,
        me: str,
        target: str,
        kind: str,
    ) -> str:
        """Open or reuse one view of a wire destination for this owner tab."""
        from toad.constants import ALL_COMMS_TARGET

        if kind == "irc" or (kind == "channel" and target == ALL_COMMS_TARGET):
            target, kind = ALL_COMMS_TARGET, "irc"
        if kind == "thread":
            return await self.open_thread_session(
                owner_mode=owner_mode,
                project_path=project_path,
                target=target,
            )

        from agent_comms.operations import wire

        from toad.screens.comms import CommsScreen

        try:
            root_path = Path(os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")).expanduser().resolve()
            comms = self.coordination_wire
            if comms.root != root_path:
                comms = wire(root_path)
            if kind == "dm":
                # DM routing needs a registered peer identity. A late action
                # may still carry a pre-rename alias; bind the canonical name.
                me = comms.registry.require(me).name
                target = comms.registry.require(target).name
            else:
                # A channel can be viewed from a local session before an ACP
                # executor is registered. Do not make that read-only view
                # depend on a non-existent worker; canonicalize when known.
                if me in comms.registry:
                    me = comms.registry.require(me).name
                target = comms.channel_catalog.resolve(target).name
        except Exception as error:
            self.notify(str(error), title="Comms target unavailable", severity="error")
            return owner_mode

        owner_screen = self._main_session_screen(owner_mode)
        if owner_screen is None or self.session_tracker.get_session(owner_mode) is None:
            # A late sidebar action must not resurrect a channel under a
            # deleted owner, or bind its Back action to an unrelated tab.
            self.notify(
                "The owning agent tab was closed",
                title="Comms target unavailable",
                severity="error",
            )
            return self.current_mode
        root = str(root_path)
        key = CommsViewKey(root, owner_mode, me, kind, target)
        if mode_name := self._comms_modes.get(key):
            try:
                self.get_screen_stack(mode_name)
            except KeyError:
                del self._comms_modes[key]
            else:
                screen = self.get_screen_stack(mode_name)[0]
                if not isinstance(screen, CommsScreen) or (
                    screen.owner_mode, screen.me, screen.kind, screen.target
                ) != (owner_mode, me, kind, target):
                    # A stale mapping is not authority to navigate through an
                    # obsolete sending identity or return to the wrong owner.
                    self.notify(
                        "Comms view changed; reopen it from the owner tab", severity="error"
                    )
                    return self.current_mode
                await self.switch_mode(mode_name)
                await screen.wait_content_ready()
                return mode_name

        owner_root = owner_screen._coordination_root if owner_screen is not None else None
        recovery_root = (
            owner_root if owner_root is not None
            and Path(owner_root).expanduser().resolve() == Path(root) else None
        )

        def get_screen() -> Screen:
            return CommsScreen(
                project_path=project_path,
                owner_mode=owner_mode,
                me=me,
                target=target,
                kind=kind,
                recovery_root=recovery_root,
            )

        self._comms_mode_index += 1
        mode_name = f"comms-{self._comms_mode_index}"

        def make_screen() -> Screen:
            screen = get_screen()
            screen.id = mode_name
            return screen

        self.add_mode(mode_name, make_screen)
        self._comms_modes[key] = mode_name
        self._open_tab_order.append(mode_name)
        self.open_tabs_changed.publish(None)
        self.update_show_sessions()
        await self.switch_mode(mode_name)
        screen = self.get_screen_stack(mode_name)[0]
        if isinstance(screen, CommsScreen):
            await screen.wait_content_ready()
        return mode_name

    async def open_file_preview(self, path: Path) -> str:
        """Open one file in the same native, closeable bar as agent/channel tabs."""
        from toad.screens.file_preview import FilePreviewScreen

        path = path.expanduser().resolve()
        if mode_name := self._file_preview_modes.get(path):
            if mode_name in self._screen_stacks:
                await self.switch_mode(mode_name)
                return mode_name
            # A removed mode must not leave a stale path-to-tab entry.
            del self._file_preview_modes[path]
            self._file_preview_return.pop(mode_name, None)
        self._file_preview_index += 1
        mode_name = f"preview-{self._file_preview_index}"

        def make_screen() -> FilePreviewScreen:
            screen = FilePreviewScreen(path)
            screen.id = mode_name
            return screen

        self.add_mode(mode_name, make_screen)
        self._file_preview_modes[path] = mode_name
        # A new preview belongs beside the tab that opened it. Reusing a file
        # changes focus only, and never shuffles an existing tab unexpectedly.
        selected = self.current_mode
        insertion = (self._open_tab_order.index(selected) + 1
                     if selected in self._open_tab_order else len(self._open_tab_order))
        self._open_tab_order.insert(insertion, mode_name)
        self.open_tabs_changed.publish(None)
        self.update_show_sessions()
        await self.switch_mode(mode_name)
        return mode_name

    async def return_from_preview(self, mode_name: str) -> None:
        """Return to the last originating tab, or another still-open view."""
        fallback = next((mode for mode in reversed(self._open_tab_order)
                         if mode != mode_name and mode in self._screen_stacks), "store")
        target = self._file_preview_return.get(mode_name)
        if target is None or target == mode_name or target not in self._screen_stacks:
            target = fallback
        await self.switch_mode(target)

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
                snapshot.thread_unread.get(name, 0) if snapshot else 0,
            ))
        tabs.extend(OpenTab(
            mode, key.title,
            (snapshot.unread if key.kind == "dm" else snapshot.channel_unread).get(key.target, 0)
            if snapshot else 0,
        ) for key, mode in self._comms_modes.items())
        tabs.extend(OpenTab(mode, path.name) for path, mode in self._file_preview_modes.items())
        by_mode = {tab.mode_name: tab for tab in tabs}
        return tuple(by_mode[mode] for mode in self._open_tab_order if mode in by_mode)

    @cached_property
    def coordination_wire(self):
        from agent_comms import wire

        return wire(Path(os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")))

    async def open_thread_session(
        self,
        *,
        owner_mode: str,
        project_path: Path,
        target: str,
    ) -> str:
        """Open or reuse a resumable wire thread as a tracked agent session."""
        from agent_comms.operations import wire

        from toad.screens.main import MainScreen

        root = Path(os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms"))
        coordination_root = str(root.expanduser().resolve())
        try:
            comms = self.coordination_wire
            if str(comms.root) != coordination_root:
                comms = wire(root)
            thread = comms.registry.require(target)
        except Exception as error:
            self.notify(str(error), title="Thread unavailable", severity="error")
            return owner_mode
        if not comms.registry.status(thread.name).active:
            source = self._main_session_screen(owner_mode)
            if source is None:
                return owner_mode
            self.notify(
                f"@{thread.name} is stopped; choose Start thread to resume it",
                title="Thread view",
            )
            return await self.open_comms_session(
                owner_mode=owner_mode, project_path=project_path,
                me=source._session_thread, target=thread.name, kind="dm",
            )
        for details in self.session_tracker.ordered_sessions:
            screen = self._main_session_screen(details.mode_name)
            if (
                screen is not None
                and screen._coordination_root == coordination_root
                and screen._session_thread == thread.name
            ):
                await self.switch_mode(details.mode_name)
                return details.mode_name

        persisted = bool(thread.session_file and Path(thread.session_file).is_file())
        attachable = thread.pid > 0 and comms._process_alive(thread.pid)
        if not persisted and not attachable:
            source = self._main_session_screen(owner_mode)
            if source is None:
                return owner_mode
            me = source._session_thread
            if thread.name == me:
                await self.switch_mode(owner_mode)
                return owner_mode
            return await self.open_comms_session(
                owner_mode=owner_mode,
                project_path=project_path,
                me=me,
                target=thread.name,
                kind="dm",
            )

        source = self._main_session_screen(owner_mode)
        if source is None:
            try:
                from toad.screens.comms import CommsScreen

                owner_screen = self.get_screen_stack(owner_mode)[-1]
                if isinstance(owner_screen, CommsScreen):
                    source = self._main_session_screen(owner_screen.owner_mode)
            except KeyError, IndexError:
                pass
        if source is None or source._agent is None:
            self.notify(
                "The owning agent session is unavailable",
                title="Thread unavailable",
                severity="error",
            )
            return owner_mode

        def get_screen() -> MainScreen:
            screen = MainScreen(
                (
                    Path(thread.worktree)
                    if Path(thread.worktree).is_dir()
                    else project_path
                ),
                source._agent,
                agent_session_id=thread.name,
                agent_session_title=thread.name,
            )
            screen._coordination_root = coordination_root
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

        details = await self.new_session_screen(get_screen)
        return details.mode_name

    def sync_coordination_identity(
        self, owner_mode: str, previous: str, current: str
    ) -> None:
        """Move open communication views to a renamed canonical thread."""
        from toad.screens.comms import CommsScreen
        from toad.widgets.comms_chat import CommsChatView
        from toad.widgets.comms_sidebar import CoordinationStatus, CommsSidebar
        from toad.widgets.recovery_view import RecoveryView
        from agent_comms.operations import wire

        for key, mode_name in list(self._comms_modes.items()):
            if key.owner_mode != owner_mode:
                continue
            if key.me != previous and wire(key.root).registry.canonical_name(key.me) != current:
                continue
            del self._comms_modes[key]
            self._comms_modes[replace(key, me=current)] = mode_name
            try:
                screen = self.get_screen_stack(mode_name)[-1]
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
                screen = self.get_screen_stack(mode_name)[-1]
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
            if screen is not None and screen._coordination_root is not None:
                threads.add(screen._session_thread)
        return threads

    async def mark_visible_thread_read(self) -> None:
        """Report the painted native cursor, never an executor's inbox cursor."""
        from toad.screens.main import MainScreen
        from toad.widgets.conversation import Conversation, Window

        screen = self.screen
        if not isinstance(screen, MainScreen):
            return
        conversation = screen.query_one_optional(Conversation)
        if conversation is None or not conversation.is_mounted:
            return
        if conversation.in_out_only:
            # Filtered-out assistant replies were not displayed. Do not
            # acknowledge an unfiltered transcript cursor on their behalf.
            return
        window = conversation.query_one_optional(Window)
        through = conversation.displayed_transcript_cursor
        if through is None or window is None or not window.follows_tail:
            return
        if any(history.is_attached and (history.has_newer or history._loading)
               for history in window.histories):
            return
        try:
            await asyncio.to_thread(
                self.coordination_wire.mark_thread_view_read, screen._session_thread,
                worktree=str(self.project_dir), through=through,
            )
        except (OSError, ValueError):
            # Source replacement or deletion is resolved by the next snapshot.
            return

    def invoke_thread_action(
        self, action: str, subject: str, actor: str, session_modes: tuple[str, ...] = ()
    ) -> None:
        """Track one UI request per thread while the core operation runs off-loop."""
        if subject in self.pending_thread_actions:
            self.notify(f"An action for @{subject} is already in progress", title="Session action")
            return
        label = {
            "comms_start": "Starting…",
            "comms_stop": "Stopping…", "comms_archive": "Archiving…",
            "comms_delete": "Deleting…", "comms_ack": "Acknowledging…",
        }.get(action, "Updating…")
        self.pending_thread_actions[subject] = label
        self.thread_actions_changed.publish(None)
        self._run_thread_action(action, subject, actor, session_modes)

    @work(group="thread-actions")
    async def _run_thread_action(
        self, action: str, subject: str, actor: str, session_modes: tuple[str, ...]
    ) -> None:
        from agent_comms import invoke_context_tool

        try:
            if action == "comms_ack":
                result = await asyncio.to_thread(
                    self.coordination_wire.mark_user_view_read,
                    subject, worktree=str(self.project_dir),
                )
                self.notify(f"Marked {subject} read", title="Session action")
            else:
                result = await asyncio.to_thread(
                    invoke_context_tool, self.coordination_wire, action, subject=subject, actor=actor
                )
            if action == "comms_start":
                self.notify(
                    f"{'Starting' if result['launched'] else 'Already running'} @{subject}",
                    title="Session action",
                )
                if result["launched"]:
                    for mode_name in session_modes:
                        screen = self._main_session_screen(mode_name)
                        if screen is not None and screen.conversation.agent is not None:
                            await screen.conversation.agent.reconnect()
                            from toad.acp.messages import TranscriptChanged
                            screen.conversation.post_message(TranscriptChanged())
            if action == "comms_delete":
                for mode_name in session_modes:
                    self.post_message(messages.SessionDelete(mode_name))
            if action == "comms_stop":
                self.notify(f"Stopped @{subject}", title="Session action")
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
                screen = self.get_screen_stack(mode_name)[-1]
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
            if self.current_mode == mode_name:
                await self.return_from_preview(mode_name)
            del self._file_preview_modes[path]
            self._file_preview_return.pop(mode_name, None)
            self._open_tab_order.remove(mode_name)
            await self.remove_mode(mode_name)
            self._prune_tab_history()
            self.open_tabs_changed.publish(None)
            self.update_show_sessions()
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
                if self.current_mode == mode_name:
                    if session_tracker.get_session(owner_mode) is not None:
                        await self.switch_mode(owner_mode)
                    else:
                        await self.switch_mode("store")
                del self._comms_modes[comms_key]
                self._open_tab_order.remove(mode_name)
                await self.remove_mode(mode_name)
                self._prune_tab_history()
                self.open_tabs_changed.publish(None)
                self.update_show_sessions()
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
        if self.current_mode not in closing_modes:
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
                await self.switch_mode("store")
        else:
            ordered_modes = [
                details.mode_name for details in session_tracker.ordered_sessions
            ]
            current_index = ordered_modes.index(mode_name)
            previous_modes = ordered_modes[:current_index]
            next_mode = next(
                (
                    candidate
                    for candidate in reversed(previous_modes)
                    if candidate not in closing_modes
                ),
                remaining_modes[0],
            )
            await self.switch_mode(next_mode)

        for closing_mode in closing_modes:
            session_tracker.close_session(closing_mode)
            await self.remove_mode(closing_mode)
        for key, comms_mode in list(self._comms_modes.items()):
            if comms_mode in closing_modes:
                del self._comms_modes[key]
        self._open_tab_order[:] = [mode for mode in self._open_tab_order if mode not in closing_modes]
        self._prune_tab_history()
        self.open_tabs_changed.publish(None)
        self.update_show_sessions()

    async def on_mount(self) -> None:
        self.capture_event("toad-run")
        self.anon_id  # Created on frst reference
        if mode := self._initial_mode:
            self.switch_mode(mode)
        else:
            await self.new_session_screen(self.get_main_screen)

        self.update_terminal_title()
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
        if self.settings.get("ui.auto_copy", bool):
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
                except (SyntaxError, ValueError):
                    href = None
                path = None
                if isinstance(href, str) and href.startswith("toad-file:"):
                    path = Path(href.removeprefix("toad-file:")).expanduser().resolve()
                elif isinstance(href, str) and href.startswith("toad-file-search:"):
                    from urllib.parse import unquote
                    from toad.conversation_markdown import _file_lookup_notice, _unique_project_file

                    name = unquote(href.removeprefix("toad-file-search:"))
                    root = Path(getattr(default_namespace.screen, "project_path", self.project_dir))
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
        from toad.version import check_version, VersionCheckFailed

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
        self.settings.set("ui.footer", visible)
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
        match self.settings.get("ui.sessions-bar", str):
            case "always":
                self.show_sessions = True
            case "never":
                self.show_sessions = False
            case "multiple":
                self.show_sessions = len(self.open_tabs) > 1

    @on(messages.SessionNavigate)
    def on_session_navigate(self, event: messages.SessionNavigate) -> None:
        modes = [tab.mode_name for tab in self.open_tabs]
        if self.current_mode in modes:
            self.switch_mode(modes[(modes.index(self.current_mode) + event.direction) % len(modes)])

    @on(messages.SessionSwitch)
    def on_session_switch(self, event: messages.SessionSwitch) -> None:
        self.switch_mode(event.mode_name)

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

                screen = self.get_screen_stack(event.source_mode)[-1]
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
            stack = self.get_screen_stack(mode_name)
        except KeyError, IndexError:
            return None
        return next(
            (screen for screen in reversed(stack) if isinstance(screen, MainScreen)),
            None,
        )

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

    @on(messages.SessionDelete)
    async def on_session_delete(self, event: messages.SessionDelete) -> None:
        screen = self._main_session_screen(event.mode_name)
        session_pk = None
        if screen is not None:
            agent = screen.conversation.agent
            session_ready_event = getattr(agent, "session_ready_event", None)
            if session_ready_event is not None and not session_ready_event.is_set():
                try:
                    await asyncio.wait_for(session_ready_event.wait(), timeout=5)
                except TimeoutError:
                    self.notify(
                        "The agent is still starting; try delete again in a moment",
                        title="Delete session",
                        severity="warning",
                    )
                    return
            session_pk = screen._session_pk
            if agent is not None:
                session_pk = getattr(agent, "session_pk", None) or session_pk
            if screen._coordination_root is not None:
                from agent_comms.operations import wire

                comms = wire(screen._coordination_root)
                thread_name = screen._session_thread
                try:
                    # Disconnect this view, then perform the explicitly requested
                    # stop/delete against the independently owned thread.
                    if agent is not None:
                        await agent.stop()
                    if thread_name in comms.registry:
                        await asyncio.to_thread(comms.stop, thread_name)
                        comms.delete(thread_name)
                except Exception as error:
                    self.notify(str(error), title="Delete thread", severity="error")
                    return
        if session_pk is not None:
            if not await DB().session_delete(session_pk):
                self.notify(
                    "Unable to delete the saved session",
                    title="Delete session",
                    severity="error",
                )
                return
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
            await self.switch_mode(sessions[-1].mode_name)
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
        from toad.screens.main import MainScreen
        from toad.agent_schema import Agent
        from toad.agents import read_agents

        agent: Agent | None = None
        session_title: str | None = None
        if session_pk is not None:
            db = DB()
            session = await db.session_get(session_pk)
            if session is not None:
                session_title = session["title"]
                meta = json.loads(session["meta_json"])
                if agent_data := meta.get("agent_data"):
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
                    getattr(live_agent, "session_id", None),
                }
                matches = agent_session_id in session_ids
                if existing._coordination_root is not None:
                    from agent_comms.operations import wire

                    comms = wire(existing._coordination_root)
                    matches = matches or (
                        comms.registry.canonical_name(agent_session_id)
                        == existing._session_thread
                    )
                if matches:
                    await self.switch_mode(details.mode_name)
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
