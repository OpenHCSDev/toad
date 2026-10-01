"""The current durable preference tree; declarations own values and effects."""

import asyncio
from functools import partial
import json
from pathlib import Path
from uuid import uuid4
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from toad import atomic, paths

from toad import setting_effects as effects
from toad.render_choices import RendererChoice, LocalRenderer
from toad.setting_choices import (
    AlwaysSessionBar,
    AutoDiff,
    BlurNotification,
    DiffMode,
    Expansion,
    FailExpansion,
    LoadingStyle,
    NormalScrollbar,
    NotificationPolicy,
    NoWrapMode,
    PulseLoading,
    Scrollbar,
    SessionBar,
    ThemeChoice,
    WrapMode,
)
from toad.settings import (
    BooleanSetting,
    ChoiceSetting,
    Group,
    IntegerSetting,
    NumberSetting,
    SettingsGroup,
    StringSetting,
    TextSetting,
    PreferenceChange,
)
from toad.widgets.presentation_window import PresentationBudget

if TYPE_CHECKING:
    from toad.app import ToadApp


def raise_save_error(error: atomic.AtomicWriteError) -> None:
    raise error


class RendererSettings(SettingsGroup):
    renderer = ChoiceSetting(
        RendererChoice,
        title="Rendering backend",
        default=LocalRenderer,
        help="CPU rendering backend for the next application launch. Persistent requires the optional extra.",
    )


class UiSettings(RendererSettings):
    history_buffer_viewports = IntegerSetting(
        title="History buffer in message-area heights",
        default=PresentationBudget().buffer_viewports,
        minimum=1,
        help="Prepare and retain this distance on both sides of the reader. Memory and widget limits still apply.",
        effect=effects.history_buffer_viewports,
    )
    theme = ChoiceSetting(
        ThemeChoice,
        title="Theme",
        default=ThemeChoice.decode("ansi-dark"),
        help="One of the builtin Textual themes. ANSI themes inherit your terminal palette.",
        effect=effects.theme,
    )
    prompt_message = StringSetting(
        title="Prompt message",
        default="How can I help you today?",
        help="Text shown as placeholder in prompt text area",
        wire_name="prompt_message",
    )
    compact_input = BooleanSetting(
        title="Compact text input?",
        default=False,
        help="Remove border and margin around the text area for additional space",
        effect=effects.compact_input,
    )
    sessions_bar = ChoiceSetting(
        SessionBar,
        title="Show sessions bar?",
        default=AlwaysSessionBar,
        help="When to show the sessions bar (tabs at top of screen).",
        effect=effects.sessions_bar,
    )
    footer = BooleanSetting(
        title="Enable footer?",
        default=True,
        help="Disable the footer if you want additional room.",
        effect=effects.footer,
    )
    info_bar = BooleanSetting(
        title="Enable info bar?",
        default=True,
        help="The info bar is the text below the prompt text area. Disable for more space.",
        effect=effects.info_bar,
    )
    status_line = BooleanSetting(
        title="Show status line in the info bar?",
        default=True,
        help="The status line shows tokens and cost (not available in all agents).",
        effect=effects.status_line,
    )
    recovery_view = BooleanSetting(
        title="Show read-only recovery status?",
        default=False,
        help="Show gateway-provided recovery status in the right sidebar when available.",
    )
    agent_title = BooleanSetting(
        title="Show agent title the info bar?",
        default=True,
        help="Disable for a little extras space.",
        effect=effects.agent_title,
    )
    column = BooleanSetting(
        title="Enable column?",
        default=False,
        help="Enable for a fixed column size. Disable to use the full screen width.",
        effect=effects.column,
    )
    column_width = IntegerSetting(
        title="Width of the column",
        default=100,
        help="Width of the column if enabled. Minimum 40 characters.",
        minimum=40,
        effect=effects.column_width,
    )
    scrollbar = ChoiceSetting(
        Scrollbar,
        title="Scrollbar size",
        default=NormalScrollbar,
        effect=effects.scrollbar,
    )
    throbber = ChoiceSetting(
        LoadingStyle,
        title="Thinking animation",
        default=PulseLoading,
        help="Animation to show while waiting for the agent to respond",
    )
    flash_duration = NumberSetting(
        title="Flash duration",
        default=3.0,
        help="Default duration of flash messages (in seconds)",
        wire_name="flash_duration",
        minimum=0.5,
    )
    auto_copy = BooleanSetting(
        title="Automatic copy",
        default=True,
        help="Automatically copy text on selection?\nDoesn't apply to text areas (use ctrl+c to copy).",
        wire_name="auto_copy",
    )
    prune_low_mark = IntegerSetting(
        title="Target lines",
        default=1500,
        help="Keep at least this many number of lines of conversation (minimum 100).",
        wire_name="prune_low_mark",
        minimum=100,
    )
    prune_excess = IntegerSetting(
        title="Additional lines",
        default=1000,
        help="Start removing lines when the conversation has this number of lines more than the target (see 'Target lines').",
        wire_name="prune_excess",
        minimum=0,
    )


class NotificationsSettings(SettingsGroup):
    system = ChoiceSetting(
        NotificationPolicy,
        title="Show Toad notifications on your desktop?",
        default=BlurNotification,
    )
    blink_title = BooleanSetting(
        title="Blink terminal title when input is required?",
        default=True,
        wire_name="blink_title",
        effect=effects.blink_title,
    )
    enable_sounds = BooleanSetting(
        title="Allow sound in notifications?", default=True, wire_name="enable_sounds"
    )
    turn_over = BooleanSetting(
        title="Desktop notification when agent has finished?",
        default=True,
        wire_name="turn_over",
    )
    hide_low_severity = BooleanSetting(
        title="Limit desktop notifications to warning and errors?",
        default=True,
        wire_name="hide_low_severity",
    )


class SidebarSettings(SettingsGroup):
    hide = BooleanSetting(title="Hide the sidebar when not in use?", default=False)
    spinner_frames_per_second = IntegerSetting(
        title="Busy sidebar animation frames per second",
        default=30,
        minimum=1,
        maximum=60,
        help="Animation cadence for busy threads. Frame stalls remain visible when the UI is occupied.",
        effect=effects.sidebar_spinner_frames_per_second,
    )
    show_stopped = BooleanSetting(
        title="Show stopped threads in Channels?",
        default=True,
        wire_name="show_stopped",
    )
    show_archived = BooleanSetting(
        title="Show archived threads in Channels?",
        default=False,
        wire_name="show_archived",
    )


class AgentSettings(SettingsGroup):
    thoughts = BooleanSetting(
        title="Agent thoughts",
        default=True,
        help="Show agent's 'thoughts' in the conversation?",
        effect=effects.thoughts,
    )


class ToolsSettings(SettingsGroup):
    expand = ChoiceSetting(
        Expansion,
        title="Tool call expand",
        default=FailExpansion,
        help="When should Toad expand tool calls?",
    )


class ShellSettings(SettingsGroup):
    command = StringSetting(
        title="Shell command",
        default="/bin/sh",
        help="Command used to launch your shell on macOS.\n[bold]Note:[/] Requires restart.",
    )
    command_start = TextSetting(
        title="Startup commands",
        default='PS1=""',
        help="Command(s) to run on shell start.",
        wire_name="command_start",
    )
    warn_dangerous = BooleanSetting(
        title="Warn against potentially destructive commands?",
        default=True,
        help="If enabled, Toad will highlight potentially destructive commands that may modify the filesystem outside of the project directory.\n\nNote that false positive [i]and[/] false negatives are possible.",
        wire_name="warn_dangerous",
    )
    allow_commands = TextSetting(
        title="Shell command completions",
        default="python\ngit\nls\ncat\ncd\nmv\ncp\ntree\nrm\necho\nrmdir\nmkdir\ntouch\nopen\npwd\nnano\nhead\ntail",
        help="Commands offered as completions after explicitly entering shell mode with !. Typing a command name in an agent prompt does not enter shell mode.",
        wire_name="allow_commands",
    )
    directory_commands = TextSetting(
        title="Directory commands",
        default="cd\nrmdir",
        help="List of commands (one per line) which accept only a directory as their first argument (used in tab completion).",
        wire_name="directory_commands",
    )
    file_commands = TextSetting(
        title="File commands",
        default="cat",
        help="List of commands (one per line) which accept only a non-directory as their first argument (used in tab completion).",
        wire_name="file_commands",
    )


class DiffSettings(SettingsGroup):
    view = ChoiceSetting(DiffMode, title="Display preference", default=AutoDiff)
    annotations = BooleanSetting(title="Show annotations (+/- symbols)?", default=False)
    wrap = ChoiceSetting(
        WrapMode,
        title="Wrap code?",
        default=NoWrapMode,
        help="If wrapping is disabled you can horizontal scroll with the trackpad or the mouse wheel plus shift.",
    )


class LauncherSettings(SettingsGroup):
    agents = TextSetting(title="Agents to show in the launcher", default="")


class StatisticsSettings(SettingsGroup):
    async def collect(self, operation: Callable[[], Awaitable[None]]) -> None:
        if self.allow_collect:
            await operation()

    allow_collect = BooleanSetting(
        title="Allow collection of anonymous usage data?",
        default=True,
        help="Toad can collect basic usage data (number of installs, OS version, agents used, session length etc). This information is associated with a randomly generated UUID (see it in /about:toad) and contains no personal information.\n\nCollecting this information will help me (Will McGugan) convince big tech to take this project seriously. I would appreciate if you left this on, but it is entirely up to you.",
        wire_name="allow_collect",
    )


class ToadSettings(SettingsGroup):
    def __init__(self, *args: Any, report_error: Callable[[atomic.AtomicWriteError], None] = raise_save_error,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.report_error = report_error
        self.save_lock = asyncio.Lock()

    @staticmethod
    def file_path() -> Path:
        return paths.get_config() / "toad.json"

    @classmethod
    def open(cls, app: ToadApp):
        path = cls.file_path()
        raw = json.loads(path.read_text("utf-8")) if path.exists() else {}
        return cls(raw, notify=partial(cls.apply_change, app),
                   report_error=partial(cls.report_failure, app))

    @staticmethod
    def apply_change(app: ToadApp, change: PreferenceChange) -> None:
        change.apply(app)
        app.settings_changed_signal.publish(change)

    @staticmethod
    def report_failure(app: ToadApp, error: atomic.AtomicWriteError) -> None:
        app.notify(str(error), title="Settings", severity="error")

    def ensure_file(self, app: ToadApp) -> None:
        path = self.file_path()
        if not path.exists():
            self.save_sync(force=True)
            if path.is_file():
                app.notify(f"Wrote default settings to {path}", title="Settings")

    def ensure_installation(self) -> bool:
        if self.anon_id:
            return False
        self.anon_id = str(uuid4())
        self.save_sync()
        return True

    async def save(self, force: bool = False) -> None:
        async with self.save_lock:
            await asyncio.to_thread(self.save_sync, force)

    async def save_before_exit(self, exit: Callable[[], None]) -> None:
        """Only the current persisted preference tree permits closing the app."""
        await self.save()
        if not self.changed:
            exit()

    def save_sync(self, force: bool = False) -> None:
        if force or self.changed:
            snapshot = self.json
            try:
                atomic.write(str(self.file_path()), snapshot)
            except atomic.AtomicWriteError as error:
                self.report_error(error)
            else:
                if self.json == snapshot:
                    self.up_to_date()

    anon_id = StringSetting(
        title="Anonymous installation ID",
        default="",
        editable=False,
        wire_name="anon_id",
    )
    ui = Group(
        UiSettings,
        title="User interface settings",
        help="The following settings allow you to customize the look and feel of the User Interface.",
    )
    notifications = Group(
        NotificationsSettings,
        title="Notification (toasts) settings",
        help="Customize how Toad displays notifications",
    )
    sidebar = Group(
        SidebarSettings,
        title="Sidebar settings",
        help="Customize how the sidebar is displayed.",
    )
    agent = Group(
        AgentSettings,
        title="Agent settings",
        help="Customize how you interact with agents",
    )
    tools = Group(
        ToolsSettings,
        title="Tool call settings",
        help="Customize how Toad displays agent tool calls",
    )
    shell = Group(
        ShellSettings, title="Shell settings", help="Customize shell interactions."
    )
    diff = Group(
        DiffSettings,
        title="Diff view settings",
        help="Customize how diffs are displayed.",
    )
    launcher = Group(
        LauncherSettings,
        title="Launcher settings",
        help="Customize the launcher",
        editable=False,
    )
    statistics = Group(
        StatisticsSettings,
        title="Data collection",
        help="Preferences regarding data collection.",
    )
