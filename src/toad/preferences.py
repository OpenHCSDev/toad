"""The user's settings: their declarations, the state that holds them, and the file.

Each setting is a dataclass field. Its type and `Annotated` metadata say what
it holds, what it is called, which values it accepts and what the app does when
it changes; the string after it is its help. `SavedSettings` keeps the values in
one ObjectState and saves them to `toad.json`.
"""

from __future__ import annotations

import asyncio
import builtins
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

from agent_comms.nominal.field_codec import FieldCodec, WireName
from agent_comms.locked_store import FilesRequest
from agent_comms.typed_table import ExternalStore
from annotated_types import Ge
from objectstate import DottedFieldPath, ObjectState, set_base_config_type
from pydantic import JsonValue
from python_introspect import AnnotatedDataclassValidationMixin, FieldLabel

from toad import atomic, paths
from toad import setting_effects as effects
from toad.forms.declared_views import DeclaredField
from toad.forms.field_path import FieldPath
from toad.forms.kinds import Multiline
from toad.key_modes import KeyMode, Standard
from toad.keymap import Keymap
from toad.patch import DiffSettings
from toad.setting_choices import (
    AlwaysSessionBar,
    BlurNotification,
    ColumnAlignment,
    Expansion,
    FailExpansion,
    LoadingStyle,
    LeftColumnAlignment,
    NormalScrollbar,
    NotificationPolicy,
    PulseLoading,
    SchemeName,
    Scrollbar,
    SessionBar,
)
from toad.setting_declarations import Effect, FamilyChoices
from toad.widgets.presentation_window import PresentationBudget

if TYPE_CHECKING:
    from toad.app import ToadApp


@dataclass(frozen=True)
class UiSettings(AnnotatedDataclassValidationMixin):
    wheel_scroll_rows: Annotated[
        int, FieldLabel("Rows per mouse wheel notch"), Ge(1), effects.wheel_scroll_rows,
        WireName("wheel-scroll-rows"),
    ] = 1
    """Vertical rows per wheel event in transcripts and sidebars. Increase for faster travel."""

    history_buffer_viewports: Annotated[
        int,
        FieldLabel("History buffer in message-area heights"),
        Ge(1),
        effects.history_buffer_viewports,
        WireName("history-buffer-viewports"),
    ] = PresentationBudget().buffer_viewports
    """Prepare and retain this distance on both sides of the reader. Memory and widget limits still apply."""

    theme: Annotated[str, SchemeName(), effects.theme] = "wal"
    """wal follows pywal's palette in true colour. ANSI themes inherit your terminal palette."""

    key_mode: Annotated[
        type[KeyMode], FieldLabel("Keyboard mode"), FamilyChoices(KeyMode),
        effects.key_mode, WireName("key-mode"),
    ] = Standard
    """Opt in to modal prompts. Escape leaves Insert; Normal Enter never sends. Ctrl+Alt+X cancels a turn."""

    keymap: Keymap = field(default_factory=Keymap)
    """Keyboard overrides, edited in the keybinding menu."""

    prompt_message: Annotated[str, FieldLabel("Prompt message")] = "How can I help you today?"
    """Text shown as placeholder in prompt text area"""

    compact_input: Annotated[
        bool, FieldLabel("Compact text input?"), effects.visibility,
        WireName("compact-input"),
    ] = False
    """Remove border and margin around the text area for additional space"""

    sessions_bar: Annotated[
        type[SessionBar],
        FieldLabel("Show sessions bar?"),
        FamilyChoices(SessionBar),
        effects.sessions_bar,
        WireName("sessions-bar"),
    ] = AlwaysSessionBar
    """When to show the sessions bar (tabs at top of screen)."""

    footer: Annotated[bool, FieldLabel("Enable footer?"), effects.visibility] = True
    """Disable the footer if you want additional room."""

    info_bar: Annotated[bool, FieldLabel("Enable info bar?"), effects.visibility, WireName("info-bar"),] = True
    """The info bar is the text below the prompt text area. Disable for more space."""

    status_line: Annotated[
        bool, FieldLabel("Show status line in the info bar?"), effects.visibility,
        WireName("status-line"),
    ] = True
    """The status line shows tokens and cost (not available in all agents)."""

    agent_title: Annotated[
        bool, FieldLabel("Show agent title the info bar?"), effects.visibility,
        WireName("agent-title"),
    ] = True
    """Disable for a little extras space."""

    column: Annotated[bool, FieldLabel("Enable column?"), effects.conversation_layout] = False
    """Enable for a fixed column size. Disable to use the full screen width."""

    column_width: Annotated[
        int, FieldLabel("Width of the column"), Ge(40), effects.conversation_layout,
        WireName("column-width"),
    ] = 100
    """Width of the column if enabled. Minimum 40 characters."""

    column_alignment: Annotated[
        type[ColumnAlignment], FieldLabel("Column alignment"),
        FamilyChoices(ColumnAlignment), effects.conversation_layout,
        WireName("column-alignment"),
    ] = LeftColumnAlignment
    """Place the conversation column on the left, in the center, or on the right."""

    scrollbar: Annotated[
        type[Scrollbar],
        FieldLabel("Scrollbar size"),
        FamilyChoices(Scrollbar),
        effects.conversation_layout,
    ] = NormalScrollbar

    throbber: Annotated[
        type[LoadingStyle], FieldLabel("Thinking animation"), FamilyChoices(LoadingStyle)
    ] = PulseLoading
    """Animation to show while waiting for the agent to respond"""

    flash_duration: Annotated[float, FieldLabel("Flash duration"), Ge(0.5)] = 3.0
    """Default duration of flash messages (in seconds)"""

    auto_copy: Annotated[bool, FieldLabel("Automatic copy")] = True
    """Automatically copy text on selection?
    Doesn't apply to text areas (use ctrl+c to copy)."""

    prune_low_mark: Annotated[int, FieldLabel("Target lines"), Ge(100)] = 1500
    """Keep at least this many number of lines of conversation (minimum 100)."""

    prune_excess: Annotated[int, FieldLabel("Additional lines"), Ge(0)] = 1000
    """Start removing lines when the conversation has this number of lines more than the target (see 'Target lines')."""


@dataclass(frozen=True)
class NotificationsSettings(AnnotatedDataclassValidationMixin):
    system: Annotated[
        type[NotificationPolicy],
        FieldLabel("Show Toad notifications on your desktop?"),
        FamilyChoices(NotificationPolicy),
    ] = BlurNotification

    blink_title: Annotated[
        bool, FieldLabel("Blink terminal title when input is required?"), effects.blink_title
    ] = True

    enable_sounds: Annotated[bool, FieldLabel("Allow sound in notifications?")] = True

    turn_over: Annotated[bool, FieldLabel("Desktop notification when agent has finished?")] = True

    hide_low_severity: Annotated[
        bool, FieldLabel("Limit desktop notifications to warning and errors?")
    ] = True


@dataclass(frozen=True)
class SidebarSettings(AnnotatedDataclassValidationMixin):
    hide: Annotated[bool, FieldLabel("Hide the sidebar when not in use?")] = False

    show_stopped: Annotated[
        bool, FieldLabel("Show stopped"), effects.sidebar_filters
    ] = True

    show_archived: Annotated[
        bool, FieldLabel("Show archived"), effects.sidebar_filters
    ] = False


@dataclass(frozen=True)
class AgentSettings(AnnotatedDataclassValidationMixin):
    thoughts: Annotated[bool, FieldLabel("Agent thoughts"), effects.visibility] = True
    """Show agent's 'thoughts' in the conversation?"""


@dataclass(frozen=True)
class ToolsSettings(AnnotatedDataclassValidationMixin):
    expand: Annotated[
        type[Expansion], FieldLabel("Tool call expand"), FamilyChoices(Expansion)
    ] = FailExpansion
    """When should Toad expand tool calls?"""


@dataclass(frozen=True)
class ShellSettings(AnnotatedDataclassValidationMixin):
    command: Annotated[str, FieldLabel("Shell command")] = "/bin/sh"
    """Command used to launch your shell on macOS.
    [bold]Note:[/] Requires restart."""

    command_start: Annotated[str, FieldLabel("Startup commands"), Multiline()] = 'PS1=""'
    """Command(s) to run on shell start."""

    warn_dangerous: Annotated[
        bool, FieldLabel("Warn against potentially destructive commands?")
    ] = True
    """If enabled, Toad will highlight potentially destructive commands that may modify the filesystem outside of the project directory.

    Note that false positive [i]and[/] false negatives are possible."""

    allow_commands: Annotated[str, FieldLabel("Shell command completions"), Multiline()] = (
        "python\ngit\nls\ncat\ncd\nmv\ncp\ntree\nrm\necho\nrmdir\nmkdir\ntouch\nopen\npwd\nnano\nhead\ntail"
    )
    """Commands offered as completions after explicitly entering shell mode with !. Typing a command name in an agent prompt does not enter shell mode."""

    directory_commands: Annotated[str, FieldLabel("Directory commands"), Multiline()] = (
        "cd\nrmdir"
    )
    """List of commands (one per line) which accept only a directory as their first argument (used in tab completion)."""

    file_commands: Annotated[str, FieldLabel("File commands"), Multiline()] = "cat"
    """List of commands (one per line) which accept only a non-directory as their first argument (used in tab completion)."""


@dataclass(frozen=True)
class LauncherSettings(AnnotatedDataclassValidationMixin):
    agents: Annotated[str, FieldLabel("Agents to show in the launcher"), Multiline()] = ""


@dataclass(frozen=True)
class StatisticsSettings(AnnotatedDataclassValidationMixin):
    allow_collect: Annotated[
        bool, FieldLabel("Allow collection of anonymous usage data?")
    ] = True
    """Toad can collect basic usage data (number of installs, OS version, agents used, session length etc). This information is associated with a randomly generated UUID (see it in /about:toad) and contains no personal information.

    Collecting this information will help me (Will McGugan) convince big tech to take this project seriously. I would appreciate if you left this on, but it is entirely up to you."""

    async def collect(self, operation: Callable[[], Awaitable[None]]) -> None:
        if self.allow_collect:
            await operation()


@dataclass(frozen=True)
class ToadSettings(AnnotatedDataclassValidationMixin):
    anon_id: str = field(default="", metadata={"ui_hidden": True})
    """Anonymous installation ID"""

    ui: Annotated[UiSettings, FieldLabel("User interface settings")] = field(
        default_factory=UiSettings
    )
    """The following settings allow you to customize the look and feel of the User Interface."""

    notifications: Annotated[
        NotificationsSettings, FieldLabel("Notification (toasts) settings")
    ] = field(default_factory=NotificationsSettings)
    """Customize how Toad displays notifications"""

    sidebar: Annotated[SidebarSettings, FieldLabel("Sidebar settings")] = field(
        default_factory=SidebarSettings
    )
    """Customize how the sidebar is displayed."""

    agent: Annotated[AgentSettings, FieldLabel("Agent settings")] = field(
        default_factory=AgentSettings
    )
    """Customize how you interact with agents"""

    tools: Annotated[ToolsSettings, FieldLabel("Tool call settings")] = field(
        default_factory=ToolsSettings
    )
    """Customize how Toad displays agent tool calls"""

    shell: Annotated[ShellSettings, FieldLabel("Shell settings")] = field(
        default_factory=ShellSettings
    )
    """Customize shell interactions."""

    diff: Annotated[DiffSettings, FieldLabel("Diff view settings")] = field(
        default_factory=DiffSettings
    )
    """Customize how diffs are displayed."""

    launcher: Annotated[LauncherSettings, FieldLabel("Launcher settings")] = field(
        default_factory=LauncherSettings, metadata={"ui_hidden": True}
    )
    """Customize the launcher"""

    statistics: Annotated[StatisticsSettings, FieldLabel("Data collection")] = field(
        default_factory=StatisticsSettings
    )
    """Preferences regarding data collection."""


# ObjectState refuses to hold any object until a process-wide root type is
# named (ObjectState issue #44).
set_base_config_type(ToadSettings)

SETTINGS = FieldPath(ToadSettings)
"""Names a setting: `SETTINGS.sidebar.hide`."""


def raise_save_error(error: atomic.AtomicWriteError) -> None:
    raise error


def no_effect(field: DeclaredField) -> None:
    """Settings held outside an app change nothing but themselves."""


class SavedSettings(ExternalStore):
    """The settings in use, the file they are saved in, and what a change does.

    One ObjectState holds the values. `current` is the typed tree to read from,
    `set` and `toggle` change one setting, and the settings form edits the same
    state. `toad.json` holds every setting the user has set, including one that
    equals its default, and no others.
    """

    def __init__(
        self,
        raw: object = None,
        *,
        root: type[ToadSettings] = ToadSettings,
        applied: Callable[[DeclaredField], None] = no_effect,
        report_error: Callable[[atomic.AtomicWriteError], None] = raise_save_error,
    ) -> None:
        from toad.core.events import CoreEventStream

        raw = {} if raw is None else raw
        self.root = FieldPath(root)
        self.state = ObjectState(FieldCodec.decode(root, raw))
        self.in_file = frozenset(self.keys_held("", raw))
        self.user_set = set(self.in_file)
        self.applied, self.report_error = applied, report_error
        self.events = CoreEventStream(self)
        self.save_lock = asyncio.Lock()
        self.open_edits: list[Callable[[], None]] = []
        self.state.on_resolved_changed(self.changed)

    # The values.

    @property
    def current(self) -> ToadSettings:
        return self.state.to_object()

    def set(self, path: FieldPath, value: object) -> None:
        setting = path.bind(self.state)
        setting.edit(value)
        self.user_set.add(setting.path)

    def toggle(self, path: FieldPath) -> None:
        setting = path.bind(self.state)
        setting.edit(not setting.value)

    def changed(self, changed: builtins.set[str]) -> None:
        from toad.core.preference_events import PreferenceChanged

        for path in self.state.parameter_structure.leaf_paths():
            if any(path.contains_path(name) for name in changed):
                setting = DeclaredField(self.state, path)
                self.user_set.add(setting.path)
                self.applied(setting)
                self.events.publish(PreferenceChanged(setting))

    def discard(self) -> None:
        """Go back to what the file holds."""
        self.state.restore_saved()
        self.user_set = set(self.in_file)

    # The file.

    @classmethod
    def path(cls) -> Path:
        return paths.get_config() / "toad.json"

    @classmethod
    def practice_opening(cls, files: FilesRequest, directory: Path) -> None:
        """An install must leave settings that this runtime can open.

        Planned reconciliation skips a file its carry will rewrite; the same
        opening check runs against the carried copy before live cutover.
        """
        resource, = cls.resources(files)
        path = files.location(resource)
        if path.exists():
            FieldCodec.decode(ToadSettings, FieldCodec.parse(path.read_text("utf-8")))

    def saved_key(self, path: DottedFieldPath) -> str:
        owner = DeclaredField(self.state, path).owner_type
        return next(key for declaration, key in FieldCodec.record_fields(owner)
                    if declaration.name == path.field_name)

    def keys_held(self, path: str, raw: object) -> list[DottedFieldPath]:
        """The settings and groups a document read from the file has a key for."""
        if not isinstance(raw, dict):
            return []
        held = []
        for below in self.state.direct_parameter_paths(path):
            if (key := self.saved_key(below)) in raw:
                held += [below, *self.keys_held(below.value, raw[key])]
        return held

    def kept(self, path: str) -> dict[str, JsonValue]:
        """The part of the whole encoded tree that belongs in the file."""
        document: dict[str, JsonValue] = {}
        for below in self.state.direct_parameter_paths(path):
            key = self.saved_key(below)
            if self.state.has_parameter_descendants(below.value):
                part = self.kept(below.value)
                if part or below in self.user_set:
                    document[key] = part
            elif below in self.user_set:
                field = DeclaredField(self.state, below)
                value = field.value
                field.validate(value)
                document[key] = FieldCodec.encode(value, field.annotation)
        return document

    def document(self) -> dict[str, JsonValue]:
        return self.kept("")

    @property
    def json(self) -> str:
        return json.dumps(self.document(), indent=4, allow_nan=False)

    @property
    def unsaved(self) -> bool:
        return self.state.is_raw_dirty or self.user_set != self.in_file

    def write(self, text: str) -> bool:
        try:
            atomic.write(str(self.path()), text)
        except atomic.AtomicWriteError as error:
            self.report_error(error)
            return False
        return True

    def written(self, text: str) -> None:
        """The file now holds this text; edits made while it was written stay unsaved."""
        if self.json == text:
            self.state.mark_saved()
            self.in_file = frozenset(self.user_set)

    def save_sync(self, force: bool = False) -> None:
        if force or self.unsaved:
            text = self.json
            if self.write(text):
                self.written(text)

    async def save(self, force: bool = False) -> None:
        for commit in self.open_edits:
            commit()
        async with self.save_lock:
            if force or self.unsaved:
                text = self.json
                if await asyncio.to_thread(self.write, text):
                    self.written(text)

    async def save_before_exit(self, exit: Callable[[], None]) -> None:
        """The app closes only when the file holds the settings in use."""
        await self.save()
        if not self.unsaved:
            exit()

    # The app.

    @classmethod
    def open(cls, app: ToadApp) -> SavedSettings:
        path = cls.path()
        raw = json.loads(path.read_text("utf-8")) if path.exists() else {}

        def applied(field: DeclaredField) -> None:
            if (effect := field.metadata(Effect)) is not None:
                effect.apply(app, field)

        def report(error: atomic.AtomicWriteError) -> None:
            app.show_error(error, "Settings")

        return cls(raw, applied=applied, report_error=report)

    def apply_all(self) -> None:
        """Bring a starting app in line with every setting."""
        for path in self.state.parameter_structure.leaf_paths():
            self.applied(DeclaredField(self.state, path))

    def ensure_file(self, app: ToadApp) -> None:
        path = self.path()
        if not path.exists():
            self.save_sync(force=True)
            if path.is_file():
                app.notify(f"Wrote default settings to {path}", title="Settings")

    def ensure_installation(self) -> bool:
        if self.current.anon_id:
            return False
        self.set(self.root.anon_id, str(uuid4()))
        self.save_sync()
        return True
