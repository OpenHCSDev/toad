from __future__ import annotations

from toad.live_output import LiveOutput, ResponseStream, ThoughtStream
from toad.transcript_publication import TranscriptPresentation
from toad.goal_interaction import GoalSession
from toad.widgets.message_filter import OtherCategory

from toad.settings import PreferenceChange
from toad.preferences import SidebarSettings, ShellSettings

import asyncio
import hashlib
from contextlib import suppress
from functools import partial
from itertools import filterfalse
from math import atan2, pi
from operator import attrgetter
from pathlib import Path
from time import monotonic, time
from typing import TYPE_CHECKING, Any, Callable, Literal

from agent_comms import agent_events as comms_events
from agent_comms.acp_extension import (
    CompactionChangedUpdate,
    CompactionPublishedUpdate,
    GoalChangedUpdate,
    InputFailedUpdate,
    InputStartedUpdate,
    McpClientReceiptUpdate,
    PendingQueueProjection,
    QueueProjection,
    TranscriptChangedUpdate,
    TranscriptSnapshotUpdate,
    TurnSettledUpdate,
    TurnStartedUpdate,
)
from agent_comms.backend import compaction_summary
from agent_comms.goal_presentation import GoalExecution
from agent_comms.mro_dispatch import MroDispatch, handles
from rich.segment import Segment
from textual import containers, events, getters, log, on, work
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.actions import SkipAction
from textual.app import ComposeResult, ScreenStackError, UnknownModeError
from textual.binding import Binding
from textual.content import Content
from textual.css.query import NoMatches
from textual.geometry import Offset, Region, clamp
from textual.layout import WidgetPlacement
from textual.layouts.grid import GridLayout
from textual.reactive import var
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static
from textual.widgets.markdown import MarkdownBlock

from toad import jsonrpc, messages, paths
from toad.acp import messages as acp_messages
from toad.acp import protocol as acp_protocol
from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation
from toad.agent import AgentBase, AgentFail, AgentReady
from toad.agent_schema import Agent as AgentData
from toad.answer import Answer
from toad.app import ToadApp
from toad.directory_watcher import DirectoryChanged, DirectoryWatcher
from toad.format_path import format_path
from toad.history import History
from toad.widgets.flash import Flash
from toad.widgets.menu import Menu
from toad.widgets.note import Note
from toad.widgets.prompt import Prompt
from toad.widgets.terminal import Terminal
from toad.widgets.throbber import Throbber
from toad.goal_display import GoalDisplay, NoGoal
from toad.session_observation import GoalObservation, InputDeliveryObservation
from toad.widgets.goal_bar import GoalBar, GoalControl
from toad.widgets.native_history import NativeHistory
from toad.widgets.observed_thread_activity import ObservedThreadActivity
from toad.widgets.session_details import SessionDetails
from toad.private_native_cursor import CursorStatus
from toad.block_navigation import admitted_blocks, ConversationBlock, ContentNavigation, UpCursor, DownCursor
from functools import cached_property
from toad.agent_presentation import AgentAttachmentView
from toad.conversation_turn import TurnOwner, ConversationTurn, AgentTurn, ClientTurn
from toad.shell import CurrentWorkingDirectoryChanged, Shell
from toad.slash_command import SlashCommand
from toad.widgets.history_anchor import HistoryWindow
from toad.widgets.input_delivery import (
    InputDeliveryBar,
    InputDeliveryDetails,
    empty_delivery,
)
from toad.widgets.user_input import UserInput
from toad.widgets.agent_response import ResponseDelivery
from toad.widgets.message_filter import all_categories, MessageCategory
from toad.layout import trim_trailing_margin
from toad.command_catalog import CommandCatalog
from toad.slash_command import AgentAdvertisedCommand, LocalCommand
from toad.menus import MenuItem
from toad.widgets.shell_terminal import ShellTerminal

AUTO_SESSION_TITLE_MAX_LENGTH = 50



def make_session_title(prompt: str) -> str:
    """Create a compact deterministic title from a session's first prompt."""
    title = " ".join(prompt.split())
    if len(title) > AUTO_SESSION_TITLE_MAX_LENGTH:
        title = title[: AUTO_SESSION_TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return title


if TYPE_CHECKING:
    from toad.acp.agent import Mode, Model
    from toad.widgets.agent_response import AgentResponse
    from toad.widgets.question import Ask
    from toad.widgets.terminal import Terminal



HELP_URL = "https://github.com/batrachianai/toad/discussions"

INTERNAL_EROR = f"""\
## Internal error

The agent reported an internal error:

```
$ERROR
```

This is likely an issue with the agent, and not Toad.

- Try the prompt again
- Report the issue to the Agent developer

Ask on {HELP_URL} if you need assistance.

"""

STOP_REASON_MAX_TOKENS = f"""\
## Maximum tokens reached

$AGENT reported that your account is out of tokens.

- You may need to purchase additional tokens, or fund your account.
- If your account has tokens, try running any login or auth process again.

If that fails, ask on {HELP_URL}
"""

STOP_REASON_MAX_TURN_REQUESTS = f"""\
## Maximum model requests reached

$AGENT has exceeded the maximum number of model requests in a single turn.

Need help? Ask on {HELP_URL}
"""

STOP_REASON_REFUSAL = f"""\
## Agent refusal
 
$AGENT has refused to continue. 

Need help? Ask on {HELP_URL}
"""


class Loading(ConversationBlock, Static):
    """Tiny widget to show loading indicator."""

    DEFAULT_CLASSES = "block"
    DEFAULT_CSS = """
    Loading {
        height: auto;        
    }
    """


class PaintOnlyRefresh:
    """Refresh progress only while its native widget is visible and current."""

    def on_mount(self) -> None:
        self.auto_refresh = 1 / 12

    def automatic_refresh(self) -> None:
        if self.is_attached and not self._closing and self.screen.is_current:
            if self in self.screen._compositor.visible_widgets:
                self.refresh(layout=False)


class ThreadLoading(ConversationBlock, PaintOnlyRefresh, Static):
    """Paint-only, viewport-scaled progress while a thread attaches."""

    DEFAULT_CSS = """
    ThreadLoading {
        width: 1fr;
        height: 1fr;
        margin: 0;
        content-align: center middle;
        color: $text-muted;
        text-style: bold;
    }
    """



    def render(self) -> Content:
        width, height = self.size
        radius = max(2, min(6, width // 12, height // 5))
        # Terminal cells are roughly 2.2 times taller than they are wide in
        # pixels. Draw the ring wider in columns so it looks circular, not a
        # vertically stretched oval, on a real terminal display.
        horizontal_radius = max(2, round(radius * 2.2))
        phase = int(monotonic() * 12) % 12
        rows = []
        for y in range(-radius, radius + 1):
            row = []
            for x in range(-horizontal_radius, horizontal_radius + 1):
                distance = (x / horizontal_radius) ** 2 + (y / radius) ** 2
                if not .7 <= distance <= 1.3:
                    row.append(" ")
                    continue
                position = int((atan2(y / radius, x / horizontal_radius) + pi) * 6 / pi) % 12
                gap = (position - phase) % 12
                row.append("●" if gap < 2 else "•" if gap < 5 else "·")
            rows.append("".join(row).strip())
        label = ("Loading new thread and history…" if width >= 32
                 else "Loading new thread…")
        block_width = max(len(label), 2 * horizontal_radius + 1)
        centered = (row.center(block_width) for row in rows)
        return Content("\n".join((*centered, "", label.center(block_width))))


class TurnActivity(Static):
    DEFAULT_CSS = "TurnActivity { height: 1; padding: 0 1; color: $text-muted; text-overflow: ellipsis; }"
    activity = var("")
    started_at: var[float | None] = var(None)

    def watch_activity(self, activity: str) -> None:
        self.display = bool(activity)
        self.auto_refresh = 1 if activity and self.started_at is not None else None
        self.refresh()

    def watch_started_at(self, _started_at: float | None) -> None:
        self.watch_activity(self.activity)

    def render(self) -> Content:
        text = " ".join(self.activity.splitlines())
        if self.started_at is not None:
            elapsed = max(0, int(time() - self.started_at))
            text += f" · {elapsed // 60}:{elapsed % 60:02d} elapsed"
        return Content(text)


class Cursor(Static):
    """The block 'cursor' -- A vertical line to the left of a block in the conversation that
    is used to navigate the discussion history.
    """

    follow_widget: var[Widget | None] = var(None)
    blink = var(True, toggle_class="-blink")

    def on_mount(self) -> None:
        self.visible = False
        self.blink_timer = self.set_interval(0.5, self._update_blink, pause=True)

    def _update_blink(self) -> None:
        if self.query_ancestor(Window).has_focus and self.screen.is_active:
            self.blink = not self.blink
        else:
            self.blink = False

    def watch_follow_widget(self, widget: Widget | None) -> None:
        self.visible = widget is not None

    def update_follow(self) -> None:
        if self.follow_widget and self.follow_widget.is_attached:
            self.styles.height = max(1, self.follow_widget.outer_size.height)
            follow_y = (
                self.follow_widget.virtual_region.y
                + self.follow_widget.parent.virtual_region.y
            )
            self.offset = Offset(0, follow_y)
        else:
            self.styles.height = None

    def follow(self, widget: Widget | None) -> None:
        self.follow_widget = widget
        self.blink = False
        if widget is None:
            self.visible = False
            self.blink_timer.reset()
            self.blink_timer.pause()
            self.styles.height = None
        else:
            self.visible = True
            self.blink_timer.reset()
            self.blink_timer.resume()
            self.update_follow()


class CategorizedMount:
    """Apply the owning conversation category selection at widget admission."""

    def mount(self, *widgets, **kwargs):
        from toad.widgets.message_filter import apply_block_filter, block_category, keep_live_block

        selected = self.query_ancestor(Conversation).visible_categories if self.is_attached else all_categories()
        for widget in admitted_blocks(widgets):
            widget.set_class(not keep_live_block(widget), "-unrouted")
            if category := block_category(widget):
                widget.add_class(f"-message-{category.declared_name}")
            apply_block_filter(widget, selected)
        return super().mount(*widgets, **kwargs)


class Contents(CategorizedMount, containers.VerticalGroup, can_focus=False):
    BLANK = True
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True


    @height_dependency(INDEPENDENT_HEIGHT)
    def process_layout(
        self, placements: list[WidgetPlacement]
    ) -> list[WidgetPlacement]:
        return trim_trailing_margin(placements)


class ContentsGrid(containers.Grid):
    BLANK = True
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True

    @height_dependency(INDEPENDENT_HEIGHT)
    def pre_layout(self, layout) -> None:
        assert isinstance(layout, GridLayout)
        layout.stretch_height = True


class CursorContainer(containers.Vertical):
    def render_lines(self, crop: Region) -> list[Strip]:
        rich_style = self.visual_style.rich_style
        strips = [Strip([Segment("▌", rich_style)], cell_length=1)] * crop.height
        if crop.y == 0 and strips:
            strips[0] = Strip([Segment(" ", rich_style)], cell_length=1)

        return strips


class ConversationWindowSettings:
    """Apply conversation preferences and subscribe tool hydration to layout."""

    def on_mount(self) -> None:
        self.app.settings_changed_signal.subscribe(self, self._settings_changed)
        self._settings_changed(PreferenceChange(SidebarSettings.hide, self.app.settings.sidebar.hide))
        self.watch(self, "scroll_y", self.hydrate_visible_tools, init=False)
        self.screen.screen_layout_refresh_signal.subscribe(self, self.on_screen_layout_refresh)

    def on_screen_layout_refresh(self, _screen) -> None:
        self.hydrate_visible_tools()

    def rebind_screen(self, previous, destination) -> None:
        """Move explicit screen-owned observers with a retained conversation."""
        previous.screen_layout_refresh_signal.unsubscribe(self)
        previous.viewport_presentation.windows.discard(self)
        destination.screen_layout_refresh_signal.subscribe(self, self.on_screen_layout_refresh)
        if viewport := self.__dict__.get("document_viewport"):
            destination.screen_layout_refresh_signal.subscribe(self, viewport.request)
            destination.viewport_presentation.windows.add(self)

    def _settings_changed(self, update: PreferenceChange) -> None:
        if update.field is SidebarSettings.hide:
            top, right, bottom, _ = self.styles.padding
            self.styles.padding = (top, right, bottom, int(self.app.settings.sidebar.hide))


class Window(ConversationWindowSettings, HistoryWindow):
    HELP = """\
## Conversation

This is a view of your conversation with the agent.

- **cursor keys** Scroll
- **alt+up / alt+down** Navigate content
- **start typing** Focus the prompt
"""
    BINDING_GROUP_TITLE = "View"
    BINDINGS = [Binding("end", "screen.focus_prompt", "Latest / prompt")]




class Conversation(containers.Vertical):
    """Holds the agent conversation (input, output, and various controls / information)."""

    BLANK = True
    MAX_LIVE_BLOCKS = 32
    BINDING_GROUP_TITLE = "Conversation"
    CURSOR_BINDING_GROUP = Binding.Group(description="Cursor")
    BINDINGS = [
        Binding(
            "alt+up",
            "cursor_up",
            "Block cursor up",
            priority=True,
            group=CURSOR_BINDING_GROUP,
            show=False,
        ),
        Binding(
            "alt+down",
            "cursor_down",
            "Block cursor down",
            group=CURSOR_BINDING_GROUP,
            show=False,
        ),
        Binding(
            "enter",
            "select_block",
            "Select",
            tooltip="Select this block",
        ),
        Binding(
            "space",
            "expand_block",
            "Expand",
            key_display="␣",
            tooltip="Expand cursor block",
        ),
        Binding(
            "space",
            "collapse_block",
            "Collapse",
            key_display="␣",
            tooltip="Collapse cursor block",
        ),
        Binding(
            "escape",
            "cancel",
            "Cancel",
            tooltip="Cancel agent's turn",
        ),
        Binding(
            "ctrl+f",
            "focus_terminal",
            "Focus",
            tooltip="Focus the active terminal",
            priority=True,
            show=False,
        ),
        Binding(
            "ctrl+o",
            "mode_switcher",
            "Modes",
            tooltip="Open the mode switcher",
        ),
        Binding(
            "ctrl+c",
            "interrupt",
            "Interrupt",
            tooltip="Interrupt running command",
        ),
    ]

    busy_count = var(0)
    visible_categories: var[frozenset[type[MessageCategory]]] = var(lambda: all_categories(), init=False)
    project_path = var("")
    working_directory: var[str] = var("")
    _blocks: var[list[MarkdownBlock] | None] = var(None)

    throbber: getters.query_one[Throbber] = getters.query_one("#throbber")
    contents = getters.query_one(Contents)
    window = getters.query_one(Window)
    cursor = getters.query_one(Cursor)
    prompt = getters.query_one(Prompt)
    app = getters.app(ToadApp)

    def watch_visible_categories(
        self, previous: frozenset[type[MessageCategory]], selected: frozenset[type[MessageCategory]],
    ) -> None:
        from toad.widgets.message_filter import apply_block_filter

        window = self.window
        self._filter_scroll_positions[previous] = (window.scroll_y, window.follows_tail)
        position = self._filter_scroll_positions.get(
            selected, (window.scroll_y, window.follows_tail)
        )
        self.navigation.index = -1
        self.screen.clear_selection()
        for block in self.contents.children:
            apply_block_filter(block, selected)
        for history in tuple(window.histories):
            history.filter.changed()
        revision = window.scroll_revision

        def restore_position():
            if (
                not self.is_attached
                or self.visible_categories != selected
                or window.scroll_revision != revision
            ):
                return
            scroll_y, following = position
            if following:
                window.anchor()
            else:
                window.release_anchor()
                window.scroll_to(y=scroll_y, animate=False, immediate=True)

        self.call_after_refresh(restore_position)

    _shell: var[Shell | None] = var(None)
    shell_history_index: var[int] = var(0, init=False)
    prompt_history_index: var[int] = var(0, init=False)

    agent: var[AgentBase | None] = var(None, bindings=True)
    agent_info: var[Content] = var(Content())
    agent_ready: var[bool] = var(False)
    modes: var[dict[str, Mode]] = var({}, bindings=True)
    current_mode: var[Mode | None] = var(None)
    models: var[dict[str, Model]] = var({}, bindings=True)
    model_history_scope = var("")
    queue_supported = var(False)
    queued_prompts: var[list[str]] = var(list)
    queue_projection: var[QueueProjection] = var(PendingQueueProjection())
    delivering_prompt = var("")
    activity = var("")
    activity_started_at: var[float | None] = var(None)
    sending_queued_prompt = var("")
    current_model: var[Model | None] = var(None)
    thinking_level = var("")
    input_delivery: var[dict] = var(empty_delivery)
    input_delivery_error: var[str] = var("")
    native_history_status: var[CursorStatus | None] = var(None)
    goal_display: var[GoalDisplay] = var(NoGoal())
    goal_execution: var[GoalExecution | None] = var(None)
    status: var[str | Content] = var("")
    column: var[bool] = var(False, toggle_class="-column")

    title = var("")

    def __init__(
        self,
        project_path: Path,
        agent: AgentData | None = None,
        agent_session_id: str | None = None,
        session_pk: int | None = None,
        session_title: str | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()

        project_path = project_path.resolve().absolute()

        self.set_reactive(Conversation.project_path, project_path)
        self.set_reactive(Conversation.working_directory, str(project_path))
        self.agent_slash_commands: list[AgentAdvertisedCommand] = []
        self.output = LiveOutput(self)
        self._loading: Loading | None = None
        self.turns = ConversationTurn(self._turn_changed)
        self._filter_scroll_positions = {}
        self._mcp_live_turn: str | None = None
        self._mcp_live_note: Note | None = None
        self._private_cursor_sequence = 0
        self._queue_sequence = 0
        self._sending_queue_input_id: str | None = None
        from toad.widgets.agent_activity import AgentActivityBoundary

        self._agent_activity_boundary = AgentActivityBoundary()
        self._last_escape_time = 0.0
        self._agent_data = agent
        self.set_class(agent is not None, "-initial-loading")
        self.set_reactive(
            Conversation.model_history_scope, agent["identity"] if agent else ""
        )
        self._agent_session_id = agent_session_id
        self._session_pk = session_pk
        self._session_title = session_title
        self._auto_title_eligible = (
            agent_session_id is None and session_pk is None and session_title is None
        )
        self._agent_fail = False
        self._mouse_down_offset: Offset | None = None

        self._focusable_terminals: list[Terminal] = []

        self.project_data_path = paths.get_project_data(project_path)
        self._prompt_history_scope = agent_session_id or (
            f"session-{session_pk}" if session_pk is not None else ""
        )
        self.shell_history = History(self.project_data_path / "shell_history.jsonl")
        self.prompt_history = History(self._prompt_history_path())

        self.session_start_time: float | None = None
        self._terminal_count = 0
        self._require_check_prune = False

        self._turn_count = 0
        self._shell_count = 0

        self._directory_changed = False
        self._directory_watcher: DirectoryWatcher | None = None

        self._initial_prompt = initial_prompt

        self.goal_observation = GoalObservation(self)
        self.goal_controls = GoalSession(self)
        self.delivery_observation = InputDeliveryObservation(self)
        self.transcript = TranscriptPresentation(self)
        self.tool_expansions: dict[str, bool] = {}
        self._compacting = False

    def remember_tool_expansion(self, tool_id: str, expanded: bool) -> None:
        """Retain bounded manual disclosure state across canonical transcript remounts."""
        self.tool_expansions.pop(tool_id, None)
        self.tool_expansions[tool_id] = expanded
        if len(self.tool_expansions) > 512:
            del self.tool_expansions[next(iter(self.tool_expansions))]

    def update_title(self) -> None:
        """Update the screen title."""

        if agent_title := self.agent_title:
            project_path = format_path(self.project_path)
            self.screen.title = f"{agent_title} {project_path}"
        else:
            self.screen.title = ""

    @property
    def agent_title(self) -> str | None:
        if self._agent_data is not None:
            return self._agent_data["name"]
        return None

    @property
    def is_watching_directory(self) -> bool:
        """Is the directory watcher enabled and watching?"""
        if self._directory_watcher is None:
            return False
        return self._directory_watcher.enabled

    def validate_shell_history_index(self, index: int) -> int:
        return clamp(index, -self.shell_history.size, 0)

    def validate_prompt_history_index(self, index: int) -> int:
        return clamp(index, -self.prompt_history.size, 0)

    def _prompt_history_path(self) -> Path:
        if not self._prompt_history_scope:
            return self.project_data_path / "prompt_history.jsonl"
        digest = hashlib.sha256(self._prompt_history_scope.encode()).hexdigest()[:16]
        return self.project_data_path / f"prompt_history-{digest}.jsonl"

    def set_prompt_history_scope(self, scope: str) -> None:
        """Use input history belonging only to one persistent thread or channel."""
        if scope == self._prompt_history_scope:
            return
        self._prompt_history_scope = scope
        self.prompt_history = History(self._prompt_history_path())
        self.prompt_history_index = 0

    def insert_path_into_prompt(self, path: Path) -> None:
        try:
            insert_path_text = str(path.relative_to(self.project_path))
        except Exception:
            self.app.bell()
            return

        insert_text = (
            f'@"{insert_path_text}"'
            if " " in insert_path_text
            else f"@{insert_path_text}"
        )
        self.prompt.prompt_text_area.insert(insert_text)
        self.prompt.prompt_text_area.insert(" ")

    def watch_project_path(self, path: Path) -> None:
        self.post_message(messages.SessionUpdate(path=str(path)))

    async def sync_project_path(self, path: Path) -> None:
        """Apply the owner's project to every cwd-bound part of this view."""
        self.project_path = path
        self.working_directory = str(path)
        self.project_data_path = paths.get_project_data(path)
        self.shell_history = History(self.project_data_path / "shell_history.jsonl")
        self.prompt_history = History(self._prompt_history_path())
        self.shell_history_index = 0
        self.prompt_history_index = 0
        if self._directory_watcher is not None:
            self._directory_watcher.stop()
            await asyncio.to_thread(self._directory_watcher.join)
            self._directory_watcher = None
        if self.agent_ready:
            self._directory_watcher = DirectoryWatcher(path, self)
            self._directory_watcher.start()
        if self._shell is not None and not self._shell.is_finished:
            with suppress(TimeoutError):
                async with asyncio.timeout(2):
                    await self._shell.change_directory(str(path))
        if self.agent is not None:
            self.agent.project_root_path = path
            if (session_pk := self.agent.session_pk) is not None:
                from toad.db import DB

                await DB().session_update_project(session_pk, path)
        self.update_title()

    async def watch_shell_history_index(self, previous_index: int, index: int) -> None:
        if previous_index == 0:
            self.shell_history.current = self.prompt.text
        try:
            history_entry = await self.shell_history.get_entry(index)
        except IndexError:
            pass
        else:
            self.prompt.text = history_entry.input
            self.prompt.shell_mode = True

    async def watch_prompt_history_index(self, previous_index: int, index: int) -> None:
        if previous_index == 0:
            self.prompt_history.current = self.prompt.text
        try:
            history_entry = await self.prompt_history.get_entry(index)
        except IndexError:
            pass
        else:
            self.prompt.text = history_entry.input

    def _turn_changed(self, owner: TurnOwner) -> None:
        if self.is_mounted:
            self.prompt.turn_owner = owner
        self.refresh_bindings()
        if owner.session_state is not None:
            self.post_message(messages.SessionUpdate(state=owner.session_state))

    @on(events.Key)
    async def on_key(self, event: events.Key):
        if (
            event.character is not None
            and event.is_printable
            and (event.character.isalnum() or event.character in "$/!")
            and self.window.has_focus
        ):
            self.prompt.focus()
            self.prompt.prompt_text_area.post_message(event)

    def compose(self) -> ComposeResult:
        from toad.widgets.transcript_history import TranscriptHistory
        with Window():
            with ContentsGrid():
                with CursorContainer(id="cursor-container"):
                    yield Cursor()
                with Contents(id="contents"):
                    if self._agent_data is not None:
                        yield ThreadLoading()
        yield Flash()
        with containers.Vertical(id="prompt-stack"):
            yield TurnActivity().data_bind(
                activity=Conversation.activity,
                started_at=Conversation.activity_started_at,
            )
            yield SessionDetails(
                self._read_thread_activity,
                read_history=lambda: self.query_one_optional(TranscriptHistory),
                history=NativeHistory().data_bind(
                    status=Conversation.native_history_status
                ),
                delivery=InputDeliveryBar().data_bind(
                    delivery=Conversation.input_delivery,
                    error=Conversation.input_delivery_error,
                ),
            )
            yield Throbber(id="throbber")
            yield GoalBar().data_bind(goal_display=Conversation.goal_display, execution=Conversation.goal_execution)
            yield Prompt().data_bind(
                project_path=Conversation.project_path,
                working_directory=Conversation.working_directory,
                agent_info=Conversation.agent_info,
                agent_ready=Conversation.agent_ready,
                current_mode=Conversation.current_mode,
                modes=Conversation.modes,
                current_model=Conversation.current_model,
                models=Conversation.models,
                model_history_scope=Conversation.model_history_scope,
                queue_supported=Conversation.queue_supported,
                queued_prompts=Conversation.queued_prompts,
                queue_projection=Conversation.queue_projection,
                delivering_prompt=Conversation.delivering_prompt,
                sending_queued_prompt=Conversation.sending_queued_prompt,
                                status=Conversation.status,
            )

    @property
    def _terminal(self) -> Terminal | None:
        """Return the last focusable terminal, if there is one.

        Returns:
            A focusable (non finalized) terminal.
        """
        # Terminals should be removed in response to the Terminal.FInalized message
        # This is a bit of a sanity check
        self._focusable_terminals[:] = list(
            filterfalse(attrgetter("is_finalized"), self._focusable_terminals)
        )

        for terminal in reversed(self._focusable_terminals):
            if terminal.display:
                return terminal
        return None

    def add_focusable_terminal(self, terminal: Terminal) -> None:
        """Add a focusable terminal.

        Args:
            terminal: Terminal instance.
        """
        if not terminal.is_finalized:
            self._focusable_terminals.append(terminal)

    @on(ShellTerminal.Interrupt)
    async def on_shell_terminal_terminate(self, event: ShellTerminal.Terminate) -> None:
        if not event.teminal.is_finalized:
            await self.shell.interrupt()
            self.navigation.index = -1
            self.flash("Command interrupted", style="success")

    @on(DirectoryChanged)
    def on_directory_changed(self, event: DirectoryChanged) -> None:
        event.stop()
        if self.turns.owner.accepts_prompt:
            self.post_message(messages.ProjectDirectoryUpdated())
        else:
            self._directory_changed = True

    @on(Terminal.Finalized)
    def on_terminal_finalized(self, event: Terminal.Finalized) -> None:
        """Terminal was finalized, so we can remove it from the list."""
        try:
            self._focusable_terminals.remove(event.terminal)
        except ValueError:
            pass

        if self._directory_changed or not self.is_watching_directory:
            self.prompt.project_directory_updated()
            self._directory_changed = False
            self.post_message(messages.ProjectDirectoryUpdated())

    @on(Terminal.LongRunning)
    def on_terminal_long_running(self, event: Terminal.LongRunning) -> None:
        if (
            not event.terminal.is_finalized
            and not event.terminal.has_focus
            and not event.terminal.state.buffer.is_blank
        ):
            self.flash("Press [b]ctrl+f[/b] to focus command", style="default")

    @on(Terminal.AlternateScreenChanged)
    def on_terminal_alternate_screen_(
        self, event: Terminal.AlternateScreenChanged
    ) -> None:
        """A terminal enabled or disabled alternate screen."""
        if event.enabled:
            event.terminal.focus()
        else:
            self.focus_prompt()

    @on(events.DescendantFocus, "Terminal")
    def on_terminal_focus(self, event: events.DescendantFocus) -> None:
        self.flash("Press [b]escape[/b] [i]twice[/] to exit terminal", style="success")

    @on(events.DescendantBlur, "Terminal")
    def on_terminal_blur(self, event: events.DescendantFocus) -> None:
        self.focus_prompt()

    @on(messages.Flash)
    def on_flash(self, event: messages.Flash) -> None:
        event.stop()
        self.flash(event.content, duration=event.duration, style=event.style)

    def flash(
        self,
        content: str | Content,
        *,
        duration: float | None = None,
        style: Literal["default", "warning", "error", "success"] = "default",
    ) -> None:
        """Flash a single-line message to the user.

        Args:
            content: Content to flash.
            style: A semantic style.
            duration: Duration in seconds of the flash, or `None` to use default in settings.
        """
        self.query_one(Flash).flash(content, duration=duration, style=style)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "focus_terminal":
            return None if self._terminal is None else True
        if action == "mode_switcher":
            return bool(self.modes)
        if action == "cancel":
            return True if (self.agent and self.turns.owner.busy) else None
        if action in {"expand_block", "collapse_block"}:
            if (cursor_block := self.cursor_block) is None:
                return False
            return cursor_block.can_expand() if action == "expand_block" else cursor_block.is_block_expanded()

        return True

    async def action_focus_terminal(self) -> None:
        if self._terminal is not None:
            self._terminal.focus()
        else:
            self.flash("Nothing to focus...", style="error")

    async def action_expand_block(self) -> None:
        if (cursor_block := self.cursor_block) is not None:
            cursor_block.expand_block()
            self.refresh_bindings()
            self.call_after_refresh(self.cursor.follow, cursor_block)

    async def action_collapse_block(self) -> None:
        if (cursor_block := self.cursor_block) is not None:
            cursor_block.collapse_block()
            self.refresh_bindings()
            self.call_after_refresh(self.cursor.follow, cursor_block)

    @cached_property
    def navigation(self) -> ContentNavigation:
        return ContentNavigation(self.contents)

    @property
    def cursor_block(self) -> ConversationBlock | None:
        return self.navigation.current

    @property
    def cursor_block_child(self) -> Widget | None:
        return self.navigation.selected

    async def _read_thread_activity(self):
        agent = self.agent
        if agent is None:
            return None
        presentation = await agent.get_thread_presentation()
        if agent is not self.agent:
            raise ValueError("Agent attachment changed")
        return presentation

    @on(ObservedThreadActivity.Changed)
    def on_observed_thread_activity(
        self, event: ObservedThreadActivity.Changed
    ) -> None:
        event.stop()
        if self.turns.managed_id is not None or self.turns.owner.busy:
            return
        if event.unavailable:
            self.post_message(
                messages.SessionUpdate(state="idle", summary="Agent status unavailable")
            )
        elif event.presentation is not None:
            self.post_message(
                messages.SessionUpdate(
                    state="busy" if event.presentation.busy else "idle",
                    summary=event.presentation.summary,
                )
            )

    @on(messages.SessionUpdate)
    def preserve_observed_activity(self, event: messages.SessionUpdate) -> None:
        """ACP readiness is not proof that a separate channel turn is idle."""
        if event.state != "idle":
            return
        observed = next(iter(self.query(ObservedThreadActivity)), None)
        if observed is None:
            return
        if observed.unavailable:
            event.summary = "Agent status unavailable"
        elif observed.presentation is not None and (
            observed.presentation.busy or observed.presentation.attention
        ):
            event.state = "busy" if observed.presentation.busy else "idle"
            event.summary = observed.presentation.summary

    @on(AgentReady)
    async def on_agent_ready(self, message: AgentReady) -> None:
        self.remove_class("-initial-loading")
        await self.query(ThreadLoading).remove()
        if not message.reconnected:
            self.session_start_time = monotonic()
            if self.agent is not None:
                content = Content.assemble(self.agent.get_info(), " connected")
                self.flash(content, style="success")
                if self._agent_data is not None:
                    self.app.capture_event(
                        "agent-session-begin",
                        agent=self._agent_data["identity"],
                    )

        self.agent_ready = True
        self.call_later(self.goal_observation.refresh)
        self.call_later(self.delivery_observation.refresh)
        self.transcript.request()
        if self.turns.managed_id is None:
            self.post_message(messages.SessionUpdate(state="idle", summary="Ready"))

    async def _apply_session_name(self, name: str) -> None:
        if self.agent is not None:
            await self.agent.set_session_name(name)
        self.post_message(messages.SessionUpdate(name=name))

    async def rename_session(self, name: str) -> None:
        """Apply an explicit user- or agent-provided title to this session."""
        self._auto_title_eligible = False
        await self._apply_session_name(name)

    async def _auto_name_from_prompt(self, prompt: str) -> None:
        if not self._auto_title_eligible:
            return
        self._auto_title_eligible = False
        if self.agent is not None and self.agent.coordination is not None:
            return
        await self._apply_session_name(make_session_title(prompt))

    @on(acp_messages.SessionInfoUpdate)
    async def on_session_info_update(
        self, message: acp_messages.SessionInfoUpdate
    ) -> None:
        message.stop()
        if (
            self.agent.coordination.wire_root
            if self.agent and self.agent.coordination
            else None
        ) is not None:
            from toad.db import DB

            self._auto_title_eligible = False
            title = message.title or ""
            if (pk := self.agent.session_pk) is not None:
                await DB().session_update_title(pk, title)
            self.post_message(messages.SessionUpdate(name=title))
        else:
            await self.rename_session(message.title or "")

    async def on_unmount(self) -> None:
        self.goal_controls.close()
        await self.transcript.close()
        self.output.retire()
        await asyncio.gather(self.goal_observation.close(), self.delivery_observation.close())
        if self._directory_watcher is not None:
            self._directory_watcher.stop()
            await asyncio.to_thread(self._directory_watcher.join)
            self._directory_watcher = None
        if self.agent is not None:
            await self.agent.retire_surface(self)

        if self._agent_data is not None and self.session_start_time is not None:
            session_time = monotonic() - self.session_start_time
            await self.app.capture_event(
                "agent-session-end",
                agent=self._agent_data["identity"],
                duration=session_time,
                agent_session_fail=self._agent_fail,
                shell_count=self._shell_count,
                turn_count=self._turn_count,
            ).wait()

    @on(AgentFail)
    async def on_agent_fail(self, message: AgentFail) -> None:
        self.remove_class("-initial-loading")
        await self.query(ThreadLoading).remove()
        self.activity = ""
        self.activity_started_at = None
        self.agent_ready = True
        self._agent_fail = True
        self.post_message(messages.SessionUpdate(state="idle", summary="Agent failed"))
        self.notify(message.message, title="Agent failure", severity="error", timeout=5)

        if self._agent_data is not None:
            self.app.capture_event(
                "agent-session-error",
                agent=self._agent_data["identity"],
                message=message.message,
                details=message.details,
            )

        if message.message:
            error = Content.assemble(
                Content.from_markup(message.message).stylize("$text-error"),
                " — ",
                Content(message.details.strip()).stylize("dim"),
            )
        else:
            error = Content(message.details.strip()).stylize("$text-error")
        await self.post(Note(error, classes="-error"))

        await message.explain(self)

    @on(messages.WorkStarted)
    def on_work_started(self) -> None:
        self.busy_count += 1

    @on(messages.WorkFinished)
    def on_work_finished(self) -> None:
        self.busy_count -= 1

    @work
    @on(messages.ChangeMode)
    async def on_change_mode(self, event: messages.ChangeMode) -> None:
        await self.set_mode(event.mode_id)

    @on(messages.ProviderLogin)
    def on_provider_login(self, event: messages.ProviderLogin):
        event.stop()
        self.action_provider_login()

    @work(group="provider-login", exclusive=True)
    async def action_provider_login(self) -> None:
        import shlex
        from textual.geometry import Offset
        from toad.screens.action_modal import ActionModal
        from toad.widgets.comms_menu import ContextMenu

        agent = self.agent
        methods = agent.presentation.auth_methods if agent is not None else []
        if not methods:
            self.flash("This agent has not advertised any login methods", style="error")
            return
        method_id = await self.app.push_screen_wait(
            ContextMenu(
                Offset(
                    self.prompt.region.x,
                    max(0, self.prompt.region.y - len(methods) - 4),
                ),
                "Connect a provider",
                [(method["id"], method["name"]) for method in methods],
            ),
            mode=self.screen.id,
        )
        if not method_id:
            self.prompt.focus()
            return
        method = next(method for method in methods if method["id"] == method_id)
        try:
            if method.get("type", "agent") == "terminal":
                command = agent.command
                if not command:
                    raise ValueError("This agent has no configured login program")
                arguments = method.get("args") or []
                command = command + (" " + shlex.join(arguments) if arguments else "")
                code = await self.app.push_screen_wait(
                    ActionModal(
                        "login",
                        self.model_history_scope,
                        method["name"],
                        command,
                        env=method.get("env") or {},
                        cwd=str(self.project_path),
                    ),
                    mode=self.screen.id,
                )
                if code != 0:
                    return
                while (
                    self.turns.owner.busy
                    or self.queued_prompts
                    or agent.presentation.prompt_in_flight
                ):
                    await asyncio.sleep(0.1)
                self.prompt.disabled = True
                if (
                    agent.coordination.wire_root
                    if agent and agent.coordination
                    else None
                ) is None:
                    await self.prune_window(0, 0)
                    self.output.boundary()
                await agent.reconnect_after_auth()
            else:
                await agent.authenticate(method_id)
            self.flash(
                "Provider login finished; model catalogue refreshed", style="success"
            )
        except (ValueError, OSError, TimeoutError, jsonrpc.JSONRPCError) as error:
            self.notify(str(error), title="Provider login", severity="error")
        finally:
            if (prompt := self.query_one_optional(Prompt)) is not None:
                prompt.disabled = False
                prompt.focus()

    @work
    @on(messages.ChangeModel)
    async def on_change_model(self, event: messages.ChangeModel) -> None:
        if self.agent is None:
            return
        if (error := await self.agent.set_model(event.model_id)) is not None:
            self.notify(error, title="Set Model", severity="error")
        elif (model := self.models.get(event.model_id)) is not None:
            from textual.geometry import Offset

            from toad.db import DB
            from toad.widgets.comms_menu import ContextMenu

            await DB().record_model_usage(self.model_history_scope, event.model_id)
            levels = self.agent.presentation.thinking_levels
            if len(levels) > 1:
                level = await self.app.push_screen_wait(
                    ContextMenu(
                        Offset(
                            self.prompt.region.x,
                            max(0, self.prompt.region.y - len(levels) - 4),
                        ),
                        f"Thinking level for {model.name}",
                        [(value, value.title()) for value in levels],
                    ),
                    mode=self.screen.id,
                )
                if (
                    level
                    and (error := await self.agent.set_thinking_level(level))
                    is not None
                ):
                    self.notify(error, title="Set thinking level", severity="error")
                    return
            self.flash(
                Content.from_markup(
                    "Model changed to [b]$model[/] · thinking [b]$level",
                    model=model.name,
                    level=self.agent.presentation.current_thinking_level or "off",
                ),
                style="success",
            )

    @on(acp_messages.ModeUpdate)
    def on_mode_update(self, event: acp_messages.ModeUpdate) -> None:
        if (modes := self.modes) is not None:
            if (mode := modes.get(event.current_mode)) is not None:
                self.current_mode = mode

    @on(messages.UserInputSubmitted)
    async def on_user_input_submitted(self, event: messages.UserInputSubmitted) -> None:
        event.stop()
        await self.submit_input(event)

    async def submit_input(self, event: messages.UserInputSubmitted) -> None:
        """Agent conversation submission; wire views override this single hook."""
        if not event.body.strip():
            if (
                event.immediate
                and not event.shell
                and self.queue_supported
                and self.queued_prompts
            ):
                # This requests scheduling, not membership mutation. Retain
                # every remote row until authoritative exact-ID evidence.
                if (
                    self.queue_projection.status == "available"
                    and self.queue_projection.items
                ):
                    first = self.queue_projection.items[0]
                    self._sending_queue_input_id = first.input_id
                    self.sending_queued_prompt = first.text
                    self.send_queued_now()
            return
        self.transcript.invalidate()
        if event.shell:
            if await self.shell.is_busy():
                if (output := self.shell.output) is not None:
                    output.focus()
                await self.shell.send_input(event.body, paste=True)
            else:
                self.shell_history.current = None
                self.run_worker(self.shell_history.append(event.body), group="history")
                self.shell_history_index = 0
                await self.post_shell(event.body)
            self.jump_to_latest()
        elif text := event.body.strip():
            if text.startswith("/") and await self.slash_command(text):
                # Toad has processed the slash command.
                return
            queued = (
                self.turns.owner.busy and self.queue_supported and not event.immediate
            )
            if event.immediate and self.queue_supported:
                self.delivering_prompt = text
            if not queued:
                await self.post(UserInput(text))
                self.jump_to_latest()
            # Local feedback precedes persistence and agent metadata work.
            self.prompt_history.current = None
            self.run_worker(self.prompt_history.append(event.body), group="history")
            self.prompt_history_index = 0
            if queued:
                self.send_prompt_to_agent(text, queued=True)
                self.flash("Queue request sent; awaiting authoritative queue state")
                return
            await self._auto_name_from_prompt(text)
            waiting = (
                "Waiting for replies…"
                if text.lstrip().startswith(("@", "#", "!relay "))
                else "Thinking…"
            )
            self.post_message(
                messages.SessionUpdate(state="busy", summary=waiting.rstrip("…"))
            )
            self.activity = waiting
            await asyncio.sleep(0)
            self.send_prompt_to_agent(text, immediate=event.immediate)

    @work(group="send-queued-now", exclusive=True)
    async def send_queued_now(self) -> None:
        try:
            if not await self.agent.send_now():
                self.sending_queued_prompt = ""
        except (jsonrpc.APIError, jsonrpc.JSONRPCError, OSError, ValueError) as error:
            self.sending_queued_prompt = ""
            self.flash(f"Send now failed: {error}", style="error")

    @work
    async def send_prompt_to_agent(
        self, prompt: str, *, queued: bool = False, immediate: bool = False
    ) -> None:
        sending_agent = self.agent
        sending_session = sending_agent.session_id
        queue = sending_agent.queue_attachment if sending_agent is not None else None
        sending_scope = queue.scope if queue is not None else None

        def current_request_owner() -> bool:
            return (
                self.agent is sending_agent
                and sending_agent.session_id == sending_session
                and (
                    queue is None
                    or (
                        queue.scope == sending_scope
                        and (
                            sending_scope is None
                            or queue.projection.status == "available"
                        )
                    )
                )
            )

        if sending_agent is not None:
            stop_reason: str | None = None
            server_owned_turn = sending_agent.coordination is not None
            if not server_owned_turn:
                self.busy_count += 1
            try:
                if not server_owned_turn:
                    self.turns.owner = AgentTurn()
                if self.queue_supported:
                    stop_reason = await sending_agent.send_prompt(
                        prompt,
                        delivery="steer" if immediate else "queue",
                        defer_display=queued,
                    )
                else:
                    stop_reason = await sending_agent.send_prompt(prompt)
            except (
                jsonrpc.APIError,
                jsonrpc.JSONRPCError,
                OSError,
                ValueError,
            ) as error:
                from toad.widgets.markdown_note import MarkdownNote

                if not current_request_owner():
                    return
                self.turns.owner = ClientTurn()

                message = (
                    str(error) or "no details were provided"
                )
                self.activity = ""
                self.activity_started_at = None
                # A send failure cannot identify/remove a remote row by text.
                self.prompt.text = "\n\n".join(filter(None, [self.prompt.text, prompt]))

                await self.post(
                    MarkdownNote(
                        INTERNAL_EROR.replace("$ERROR", message),
                        classes="-stop-reason",
                    )
                )
            finally:
                if (
                    current_request_owner()
                    and immediate
                    and self.delivering_prompt == prompt
                ):
                    self.delivering_prompt = ""
                if not server_owned_turn:
                    self.busy_count -= 1
            if current_request_owner() and not server_owned_turn:
                self.call_later(self.agent_turn_over, stop_reason)

    async def agent_turn_over(self, stop_reason: str | None) -> None:
        """Called when the agent's turn is over.

        Args:
            stop_reason: The stop reason returned from the Agent, or `None`.
        """
        self.turns.owner = ClientTurn()
        self._agent_activity_boundary.reset()
        self.activity = ""
        self.activity_started_at = None
        if stop_reason == "end_turn" and self.current_model is not None:
            from toad.db import DB

            await DB().record_model_usage(
                self.model_history_scope, self.current_model.id
            )
        await self.output.settle()
        pending_loading, self._loading = self._loading, None
        if pending_loading is not None and pending_loading.is_attached:
            await pending_loading.remove()
        self.output.boundary()

        if self._directory_changed or not self.is_watching_directory:
            self._directory_changed = False
            self.post_message(messages.ProjectDirectoryUpdated())
            self.prompt.project_directory_updated()

        self._turn_count += 1

        self.post_message(
            messages.SessionUpdate(state="idle", summary="Ready for review")
        )

        if stop_reason != "end_turn":
            from toad.widgets.markdown_note import MarkdownNote

            agent = (self.agent_title or "agent").title()

            if stop_reason == "max_tokens":
                await self.post(
                    MarkdownNote(
                        STOP_REASON_MAX_TOKENS.replace("$AGENT", agent),
                        classes="-stop-reason",
                    )
                )
            elif stop_reason == "max_turn_requests":
                await self.post(
                    MarkdownNote(
                        STOP_REASON_MAX_TURN_REQUESTS.replace("$AGENT", agent),
                        classes="-stop-reason",
                    )
                )
            elif stop_reason == "refusal":
                await self.post(
                    MarkdownNote(
                        STOP_REASON_REFUSAL.replace("$AGENT", agent),
                        classes="-stop-reason",
                    )
                )

        if self.app.settings.notifications.turn_over:
            self.app.system_notify(
                f"{self.agent_title} has finished working",
                title="Waiting for input",
                sound="turn-over",
            )

    @on(Menu.OptionSelected)
    async def on_menu_option_selected(self, event: Menu.OptionSelected) -> None:
        event.stop()
        event.menu.display = False
        if event.action is not None:
            await self.run_action(event.action, {"block": event.owner})
        if (cursor_block := self.cursor_block_child) is not None:
            self.call_after_refresh(self.cursor.follow, cursor_block)
        self.call_after_refresh(event.menu.remove)

    @on(Menu.Dismissed)
    async def on_menu_dismissed(self, event: Menu.Dismissed) -> None:
        event.stop()
        if event.menu.has_focus:
            self.window.focus(scroll_visible=False)
        await event.menu.remove()

    @on(CurrentWorkingDirectoryChanged)
    def on_current_working_directory_changed(
        self, event: CurrentWorkingDirectoryChanged
    ) -> None:
        if self._shell is None or self._shell.pending_directory is None:
            self.working_directory = str(Path(event.path).resolve().absolute())

    async def watch_busy_count(self, busy: int) -> None:
        if (throbber := self.query_one_optional("#throbber", Throbber)) is not None:
            throbber.busy = busy > 0

    @on(acp_messages.UpdateStatusLine)
    async def on_update_status_line(self, message: acp_messages.UpdateStatusLine):
        self.status = message.status_line

    @on(acp_messages.RejectedSessionUpdate)
    async def on_rejected_session_update(
        self, message: acp_messages.RejectedSessionUpdate
    ) -> None:
        message.stop()
        self.output.boundary()
        await self.post(
            Note(
                Content.styled("Invalid ACP update rejected", "$text-error"),
                classes="-error",
            )
        )

    async def _clear_mcp_live(self) -> None:
        self._mcp_live_turn = None
        if self._mcp_live_note is not None:
            await self._mcp_live_note.remove()
            self._mcp_live_note = None

    def on_private_native_cursor_update(
        self, message: acp_messages.CommsUpdated
    ) -> None:
        message.stop()
        if (
            message.agent is not self.agent
            or self.agent is None
            or message.session_id != self.agent.session_id
            or message.sequence <= self._private_cursor_sequence
        ):
            return
        self._private_cursor_sequence = message.sequence
        self.native_history_status = message.update.status

    @on(acp_messages.McpClientStopped)
    async def on_mcp_client_stopped(
        self, message: acp_messages.McpClientStopped
    ) -> None:
        message.stop()
        if message.agent is self.agent:
            await self._clear_mcp_live()

    async def on_mcp_client_status(self, message: acp_messages.CommsUpdated) -> None:
        """Render the turn-bound receipt only inside an active server-owned turn."""
        # The message carries the validated turn identity; a delayed or queued
        # message from an older agent cannot attach to a successor turn here.
        agent_session = self.agent.session_id if self.agent else None
        if (
            message.agent is not self.agent
            or (self.agent._active_turn_id if self.agent else None)
            != message.update.turn_id
            or self.turns.managed_id is None
            or message.update.turn_id != self.turns.managed_id
            or (agent_session is not None and message.session_id != agent_session)
        ):
            # Late or forged: the projection dies with its turn and is never
            # shown outside the active-turn lifetime.
            return
        if self._mcp_live_turn == self.turns.managed_id:
            return  # The package emits at most one receipt per turn.
        self._mcp_live_turn = self.turns.managed_id
        rows = message.update.receipt.servers
        summary = (
            "; ".join(
                f"{row.id}[{row.scope}] {row.state.declared_name} calls={row.calls.declared_name}"
                f" tools={row.tools} resources={row.resources} prompts={row.prompts}"
                for row in rows
            )
            or "no approved servers"
        )
        self.output.boundary()
        self._mcp_live_note = Note(
            Content.styled(
                f"MCP live (this turn, not a grant): {summary}", "$text-muted"
            ),
        )
        await self.post(self._mcp_live_note)

    @on(acp_messages.Update)
    async def on_acp_agent_message(self, message: acp_messages.Update):
        from toad.widgets.agent_response import AgentResponse

        message.stop()
        if not self.turns.owner.busy:
            # Owner notices (including manual compaction) are complete messages,
            # not a live response waiting for a future turn-settled event.
            await self.post(AgentResponse(message.text, delivery=ResponseDelivery.from_route(message.route)))
            return
        if self.turns.owner.busy:
            self.activity = "Writing response…"
            self.post_message(
                messages.SessionUpdate(state="busy", summary="Writing response")
            )
        await self.output.append(ResponseStream(ResponseDelivery.from_route(message.route)), message.text)

    async def on_turn_started(self, message: acp_messages.CommsUpdated) -> None:
        previous = self.turns.start(message, self.agent)
        if previous is None:
            return
        update = message.update
        self.activity_started_at = update.started_at
        self.activity = update.activity_detail or "Thinking…"
        self.transcript.invalidate()
        if previous.managed_id is None:
            self.busy_count += 1
        await self._clear_mcp_live()
        self._agent_activity_boundary.reset()
        self.app.open_tabs_changed.publish(None)
        self.output.boundary()
        self.post_message(messages.SessionUpdate(state="busy", summary=self.activity))

    async def on_turn_settled(self, message: acp_messages.CommsUpdated) -> None:
        previous = self.turns.settle(message, self.agent)
        if previous is None:
            return
        await self._clear_mcp_live()
        self.delivering_prompt = ""
        self.sending_queued_prompt = ""
        self.activity = ""
        self.activity_started_at = None
        self.app.open_tabs_changed.publish(None)
        if message.update.turn_id is not None:
            if previous.managed_id is not None:
                self.busy_count -= 1
                await self.agent_turn_over("end_turn")
                return
            self.output.boundary()
        self.post_message(messages.SessionUpdate(state="idle", summary="Ready for review"))

    async def on_queue_view_update(self, message: acp_messages.CommsUpdated) -> None:
        if (
            self.agent is None
            or message.agent is not self.agent
            or message.session_id != self.agent.session_id
            or message.sequence <= self._queue_sequence
        ):
            return
        self._queue_sequence = message.sequence
        self.queue_projection = message.update.projection
        self.queued_prompts = [row.text for row in message.update.projection.items]
        for started in message.update.starts:
            if (
                message.agent is not self.agent
                or message.session_id != self.agent.session_id
            ):
                return
            if started.input_id == self._sending_queue_input_id:
                self._sending_queue_input_id = None
                self.sending_queued_prompt = ""
            self.output.boundary()
            await self.post(UserInput(started.text))

    async def on_input_started(self, message: acp_messages.CommsUpdated):
        if (
            self.agent is None
            or message.agent is not self.agent
            or message.session_id != self.agent.session_id
        ):
            return
        if message.update.text is not None:
            self.output.boundary()
            await self.post(UserInput(message.update.text))

    def on_input_failed(self, message: acp_messages.CommsUpdated) -> None:
        """Only a locally failed request may recover its own draft text."""
        if (
            self.agent is None
            or message.agent is not self.agent
            or message.session_id != self.agent.session_id
        ):
            return
        queue = self.agent.queue_attachment
        if message.recover_draft and (
            message.queue_scope != (queue.scope if queue is not None else None)
            or (
                message.queue_scope is not None
                and queue.projection.status != "available"
            )
        ):
            return
        if not message.recover_draft:
            # Server notices (including unstarted queued/restored inputs) are
            # read-only evidence, not permission to change the local composer.
            self.flash(
                f"{message.update.failure.title}: {message.update.failure.description}\n{message.update.failure.input_disposition}\n{message.update.failure.action}",
                style="error",
            )
            return
        if message.update.text and not (
            self.prompt.text == message.update.text
            or self.prompt.text.endswith("\n\n" + message.update.text)
        ):
            self.prompt.text = "\n\n".join(
                filter(None, [self.prompt.text, message.update.text])
            )
        self.delivering_prompt = ""
        self.flash(
            f"{message.update.failure.title}; draft restored: {message.update.failure.description}\n{message.update.failure.input_disposition}\n{message.update.failure.action}",
            style="error",
        )

    async def on_transcript_history_covered(self, message) -> None:
        message.stop()
        await self.transcript.covered(message)

    @on(acp_messages.Thinking)
    async def on_acp_agent_thinking(self, message: acp_messages.Thinking):
        message.stop()
        self.activity = "Thinking…"
        activity = " ".join(message.text.splitlines()).strip() or "Thinking"
        self.post_message(messages.SessionUpdate(state="busy", summary=activity))
        await self.output.append(ThoughtStream(), message.text)

    @on(acp_messages.RequestPermission)
    async def on_acp_request_permission(self, message: acp_messages.RequestPermission):
        message.stop()
        self.request_permissions(message.request)
        self.output.boundary()

    @on(acp_messages.Plan)
    async def on_acp_plan(self, message: acp_messages.Plan):
        from toad.widgets.plan import Plan

        entries = [
            Plan.Entry(
                Content(entry["content"]),
                entry.get("priority", "medium"),
                entry.get("status", "pending"),
            )
            for entry in message.entries
        ]

        if self.contents.children and isinstance(
            (current_plan := self.contents.children[-1]), Plan
        ):
            current_plan.entries = entries
        else:
            await self.post(Plan(entries))

    @on(acp_messages.ToolCallUpdate)
    @on(acp_messages.ToolCall)
    async def on_acp_tool_call_update(
        self, message: acp_messages.ToolCall | acp_messages.ToolCallUpdate
    ):
        from toad.widgets.tool_call import ToolCall

        tool_call = message.tool_call
        status = tool_call.get("status")
        title = tool_call.get("title") or "Using tool"
        if status in {None, "pending", "in_progress"}:
            self.activity = " ".join(title.splitlines())
            self.post_message(messages.SessionUpdate(state="busy", summary=title))

        if status in (None, "completed"):
            self.output.boundary()

        tool_id = message.tool_id
        try:
            existing_tool_call: ToolCall | None = self.contents.get_child_by_id(
                tool_id, ToolCall
            )
        except NoMatches:
            await self.post(ToolCall(tool_call, id=message.tool_id), new_block=True)
        else:
            if existing_tool_call is not None:
                await existing_tool_call.update_tool_call(tool_call)

    @on(acp_messages.AvailableCommandsUpdate)
    async def on_acp_available_commands_update(
        self, message: acp_messages.AvailableCommandsUpdate
    ):
        self.agent_slash_commands = [
            AgentAdvertisedCommand.from_acp(record) for record in message.commands
        ]
        self.update_slash_commands()

    async def action_interrupt(self) -> None:
        terminal = self._terminal
        if terminal is not None and not terminal.is_finalized:
            await self.shell.interrupt()
            # self._shell = None
            self.flash("Command interrupted", style="success")
        else:
            raise SkipAction()

    def action_focus_block(self, block_id: str) -> None:
        with suppress(NoMatches):
            self.query_one(f"#{block_id}").focus()

    async def set_mode(self, mode_id: str | None) -> None:
        """Set the mode give its id (if it exists).

        Args:
            mode_id: Id of mode.

        Returns:
            `True` if the mode was changed, `False` if it didn't exist.
        """
        if (agent := self.agent) is None:
            return
        if mode_id is None:
            self.current_mode = None
        else:
            if (error := await agent.set_mode(mode_id)) is not None:
                self.notify(error, title="Set Mode", severity="error")
            elif (new_mode := self.modes.get(mode_id)) is not None:
                self.current_mode = new_mode
                self.flash(
                    Content.from_markup("Mode changed to [b]$mode", mode=new_mode.name),
                    style="success",
                )

    @on(acp_messages.SetModes)
    async def on_acp_set_modes(self, message: acp_messages.SetModes):
        self.modes = message.modes
        self.current_mode = self.modes[message.current_mode]

    @on(acp_messages.SetModels)
    async def on_acp_set_models(self, message: acp_messages.SetModels):
        self.models = message.models
        self.current_model = self.models.get(message.current_model)
        self._update_model_info()

    @on(acp_messages.SetThinkingLevels)
    def on_acp_set_thinking_levels(self, message: acp_messages.SetThinkingLevels):
        self.thinking_level = message.current_level
        self._update_model_info()

    def _update_model_info(self) -> None:
        if self.current_model is not None:
            suffix = f" · {self.thinking_level}" if self.thinking_level else ""
            self.agent_info = Content(self.current_model.name + suffix)
        else:
            self.agent_info = (
                self.agent.get_info() if self.agent is not None else Content()
            )

    @on(messages.HistoryMove)
    async def on_history_move(self, message: messages.HistoryMove) -> None:
        message.stop()
        if message.shell:
            await self.shell_history.open()

            if self.shell_history_index == 0:
                current_shell_command = ""
            else:
                current_shell_command = (
                    await self.shell_history.get_entry(self.shell_history_index)
                ).input
            while True:
                self.shell_history_index += message.direction
                new_entry = await self.shell_history.get_entry(self.shell_history_index)
                if new_entry.input != current_shell_command:
                    break
                if message.direction == +1 and self.shell_history_index == 0:
                    break
                if (
                    message.direction == -1
                    and self.shell_history_index <= -self.shell_history.size
                ):
                    break
        else:
            await self.prompt_history.open()
            self.prompt_history_index += message.direction

    @work
    async def request_permissions(self, request) -> None:
        await request.presentation.present(self, request)

    async def post_tool_call(
        self, tool_call_update: acp_protocol.ToolCallUpdate
    ) -> None:
        if (contents := tool_call_update.get("content")) is None:
            return

        for content in contents:
            match content:
                case {
                    "type": "diff",
                    "oldText": old_text,
                    "newText": new_text,
                    "path": path,
                }:
                    await self.post_diff(path, old_text, new_text)

    async def post_diff(self, path: str, before: str | None, after: str) -> None:
        """Post a diff view.

        Args:
            path: Path to the file.
            before: Content of file before edit.
            after: Content of file after edit.
        """

        from toad.widgets.diff_view import make_diff

        diff_view = make_diff(path, path, before, after, classes="block")
        await self.post(diff_view)

    def ask(
        self,
        options: list[Answer],
        title: str = "",
        get_content: Callable[[], Widget] | None = None,
        callback: Callable[[Answer], Any] | None = None,
    ) -> Ask:
        """Replace the prompt with a dialog to ask a question

        Args:
            question: Question to ask or empty string to omit.
            options: A list of (ANSWER, ANSWER_ID) tuples.
            callback: Optional callable that will be invoked with the result.
        """
        from toad.widgets.question import Ask

        self.agent_info

        if self.agent_title:
            notify_title = f"[{self.agent_title}] {title}"
        else:
            notify_title = title
        notify_message = "\n".join(f" • {option.text}" for option in options)
        self.app.system_notify(notify_message, title=notify_title, sound="question")

        ask = Ask(title, options, get_content, callback)
        self.prompt.ask(ask)
        return ask

    def command_target_context(self):
        from toad.navigation_target import NavigationOwner
        from toad.target_commands import ThreadContext
        if not isinstance(self.screen, NavigationOwner):
            return None
        nav = self.screen.navigation_context
        comms = self.app.coordination_wire
        from agent_comms.errors import UnregisteredThreadError
        try:
            comms.registry.require(nav.actor)
        except UnregisteredThreadError:
            return None
        return ThreadContext(self.app, comms, nav.actor, nav.actor, nav.project_path, nav.owner_mode)

    def update_slash_commands(self) -> None:
        """Update slash commands, which may have changed since mounting."""
        self.prompt.slash_commands = CommandCatalog(
            self.agent_slash_commands, self.command_target_context()
        ).commands

    async def on_mount(self) -> None:
        self.set_interval(1, lambda: self.goal_controls.poll())
        await self.initialize_view()

    async def initialize_view(self) -> None:
        """Initialize the agent view, separate from the framework mount event."""
        self.trap_focus()
        self.watch(self.window, "scroll_y", self._history_scroll_changed, init=False)
        self.prompt.focus()
        self.prompt.slash_commands = CommandCatalog(
            self.agent_slash_commands, self.command_target_context()
        ).commands
        self.call_after_refresh(self.post_welcome)
        self.app.settings_changed_signal.subscribe(self, self._settings_changed)
        self.app.open_tabs_changed.subscribe(self, self._coordination_changed)

        self.shell_history.complete.add_words(
            self.app.settings.shell.allow_commands.split()
        )
        if self._agent_data is not None:

            async def start_agent() -> None:
                """Start the agent after refreshing the UI."""
                assert self._agent_data is not None
                from toad.acp.agent import Agent

                self.agent = Agent(
                    self.project_path,
                    self._agent_data,
                    self._agent_session_id,
                    self._session_pk,
                )
                await self.agent.start(self)
                self.post_message(
                    messages.SessionUpdate(
                        self._session_title or "New Session", self.agent_title
                    )
                )

            from toad.screens.session_view import SessionView

            screen = self.screen
            if isinstance(screen, SessionView):
                screen.call_after_first_frame(self, start_agent)
            else:
                self.call_after_refresh(start_agent)

        else:
            self.agent_ready = True

        self.update_title()
        self.window.anchor()

    def _history_scroll_changed(self, _position: float) -> None:
        self.call_after_refresh(self.transcript.retry)

    @property
    def unresolved_inputs(self) -> list[dict]:
        return self.input_delivery["inputs"]

    def on_input_dispositions_changed(
        self, event: acp_messages.InputDispositionsChanged
    ) -> None:
        event.stop()
        self.delivery_observation.invalidate()

    @on(InputDeliveryBar.Inspect)
    async def inspect_input_delivery(self, event: InputDeliveryBar.Inspect) -> None:
        event.stop()
        await self.delivery_observation.refresh()
        details = InputDeliveryDetails(
            log_path=self.agent.presentation.log_path if self.agent is not None else None,
            load_history=self.delivery_observation.history,
            dismiss_history=self.delivery_observation.dismiss_history,
        )
        # A modal remains a view of the same backend snapshot, including later starts.
        details.delivery = self.input_delivery
        details.error = self.input_delivery_error
        session_details = self.query_one_optional(SessionDetails)
        if session_details is not None:
            details.overview_text = session_details.overview_text
        self.app.push_screen(details)
        details.watch(
            self, "input_delivery", lambda state: setattr(details, "delivery", state)
        )
        details.watch(
            self, "input_delivery_error", lambda error: setattr(details, "error", error)
        )
        if session_details is not None:
            details.watch(
                session_details,
                "overview_text",
                lambda value: setattr(details, "overview_text", value),
            )

    @on(acp_messages.CommsUpdated)
    async def on_comms_updated(self, event: acp_messages.CommsUpdated) -> None:
        if event.agent is not None and (
            event.agent is not self.agent or event.session_id != self.agent.session_id
        ):
            event.stop()
            return
        await ConversationCommsConsumer(self, event).dispatch(event.update)

    async def _coordination_changed(self, _update: None) -> None:
        self.update_slash_commands()
        await self.goal_observation.refresh()

    @on(GoalControl.Activated)
    async def on_goal_control(self, event: GoalControl.Activated):
        event.stop()
        await self.goal_controls.activate(event.action)

    @work(group="context-compaction")
    async def compact_context(self, instructions: str | None) -> None:
        """Keep processing owner notifications while compaction is in flight."""
        from toad.widgets.agent_response import AgentResponse

        try:
            self.window.anchor()
            self.flash("Compaction requested")
            await self.agent.compact_context(instructions)
            self.flash("Context compacted", style="success")
        except (OSError, ValueError, jsonrpc.JSONRPCError) as error:
            await self.post(
                AgentResponse(
                    f"## Compaction failed\n\n{error}", category=OtherCategory
                )
            )
        finally:
            self._compacting = False

    def open_queue_menu(self) -> None:
        """Remote edits require exact input IDs and backend revision-CAS support."""
        if self.queued_prompts:
            self._queue_edit_unavailable()

    def _queue_edit_unavailable(self) -> None:
        self.flash(
            "Remote queue editing unavailable: requires ID-targeted, revision-checked backend support",
            style="error",
        )

    def _on_queue_choice(self, action: str | None) -> None:
        # A stale menu callback must not edit the draft or mutate the remote
        # queue. Text/index matching cannot identify an admitted input safely.
        if action:
            self._queue_edit_unavailable()

    @work
    async def replace_queued(self, prompts: list[str]) -> None:
        """Never clear-and-resend admitted inputs when editing the queue.

        An empty snapshot or control ACK does not prove consumption, and a
        surviving row may be UNKNOWN. Reissuing its text could execute it twice.
        Local unsent composer drafts remain editable without touching this API.
        """
        self._queue_edit_unavailable()

    def _settings_changed(self, change: PreferenceChange) -> None:
        if change.field is ShellSettings.allow_commands:
            self.shell_history.complete.add_words(
                self.app.settings.shell.allow_commands.split()
            )

    @work
    async def post_welcome(self) -> None:
        """Post any welcome content."""

    def watch_agent(self, agent: AgentBase | None) -> None:
        self.transcript.source_changed()
        # A presentation remount is not a fresh attachment. Start at the
        # Agent's current projection/floor so previously queued receipts cannot
        # revive proof after its reducer entered quarantine or evidence loss.
        if agent is not None:
            agent.attach_surface(self)
        attachments = (agent.presentation.attachments if agent is not None
                       else AgentAttachmentView(None, 0, PendingQueueProjection(), 0))
        self.native_history_status = attachments.cursor
        self._private_cursor_sequence = attachments.cursor_sequence
        self.queue_projection = attachments.queue
        self.queued_prompts = [row.text for row in self.queue_projection.items]
        self._queue_sequence = attachments.queue_sequence
        self._sending_queue_input_id = None
        self.sending_queued_prompt = ""
        if agent is None:
            self.agent_info = Content.styled("shell")
        else:
            self.agent_info = agent.get_info()
            self.agent_ready = agent.ready
            self.turns.owner = agent.current_turn
            self.busy_count = int(self.turns.owner.busy)
            if self.agent_ready:
                self.call_later(self.goal_observation.refresh)
                self.call_later(self.delivery_observation.refresh)
        self.update_title()

    @work
    async def watch_agent_ready(self, ready: bool) -> None:
        if ready and self._directory_watcher is None:
            self._directory_watcher = DirectoryWatcher(self.project_path, self)
            self._directory_watcher.start()
        if ready and (agent_data := self._agent_data) is not None:
            welcome = agent_data.get("welcome", None)
            if welcome is not None:
                from toad.widgets.markdown_note import MarkdownNote

                await self.post(MarkdownNote(welcome))
        if ready and self._initial_prompt is not None:
            prompt = self._initial_prompt
            if prompt.startswith("!"):
                self.post_message(
                    messages.UserInputSubmitted(self._initial_prompt[1:], shell=True)
                )
            else:
                self.post_message(
                    messages.UserInputSubmitted(self._initial_prompt, shell=False)
                )
            self._initial_prompt = None

    def on_resize(self) -> None:
        # A goal can retain its own size while the surrounding viewport changes.
        # Reapply its user-selected height against the new viewport bound.
        if (goal_bar := self.query_one_optional(GoalBar)) is not None:
            goal_bar.update_document_height()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._mouse_down_offset = event.screen_offset
        if (goal_bar := self.query_one_optional(GoalBar)) is not None:
            goal_bar.begin_separator_resize(event)

    def on_click(self, event: events.Click) -> None:
        if (
            self._mouse_down_offset is not None
            and event.screen_offset != self._mouse_down_offset
        ):
            return
        widget = event.widget

        if self.screen.get_selected_text():
            return
        if widget is None or widget.is_maximized:
            return
        try:
            widget.query_ancestor(Prompt)
        except NoMatches:
            pass
        else:
            return

        if self.navigation.select(widget):
            self.refresh_block_cursor()

    async def post[WidgetType: Widget](
        self,
        widget: WidgetType,
        *,
        loading: bool = False,
        new_block: bool = True,
    ) -> WidgetType:
        """Post a widget to the converstaion.

        Args:
            widget: Widget to post.
            loading: Set the widget to an initial loading state?
            new_block: Start a new block?

        Returns:
            The widget that was mounted.
        """
        pending_loading, self._loading = self._loading, None
        if pending_loading is not None and pending_loading.is_attached:
            await pending_loading.remove()
        if new_block and not loading:
            self.output.boundary()
        if not self.contents.is_attached:
            return widget
        from toad.widgets.message_divider import AgentActivityDivider
        from toad.widgets.message_filter import block_category

        category = block_category(widget)
        if self._agent_activity_boundary.observe(category):
            assert category is not None
            await self.contents.mount(AgentActivityDivider(category), widget)
        else:
            await self.contents.mount(widget)

        widget.loading = loading
        self._require_check_prune = True
        self.call_after_refresh(self.check_prune)
        return widget

    async def check_prune(self) -> None:
        """Check if a prune is required."""
        if self._require_check_prune:
            self._require_check_prune = False
            low_mark = self.app.settings.ui.prune_low_mark
            high_mark = low_mark + self.app.settings.ui.prune_excess
            await self.prune_window(low_mark, high_mark)

    async def prune_window(self, low_mark: int, high_mark: int) -> None:
        """Remove older children to keep within a certain range.

        Args:
            low_mark: Height to aim for.
            high_mark: Height to start pruning.
        """

        assert high_mark >= low_mark

        contents = self.contents

        height = contents.virtual_size.height
        if height <= high_mark:
            return
        prune_children: list[Widget] = []
        bottom_margin = 0
        prune_height = 0

        if low_mark == 0:
            prune_children = list(contents.children)
        else:
            for child in contents.children:
                if not child.display:
                    prune_children.append(child)
                    continue
                top, _, bottom, _ = child.styles.margin
                child_height = child.outer_size.height
                prune_height = (
                    (prune_height - bottom_margin + max(bottom_margin, top))
                    + bottom
                    + child_height
                )
                bottom_margin = bottom
                if height - prune_height <= low_mark:
                    break
                prune_children.append(child)

        self.navigation.index = -1
        self.cursor.visible = False
        self.cursor.follow(None)
        contents.refresh(layout=True)

        if prune_children:
            await contents.remove_children(prune_children)

        self.call_later(self.window.anchor)

    async def new_terminal(self) -> Terminal:
        """Create a new interactive Terminal.

        Args:
            width: Initial width of the terminal.
            display: Initial display.

        Returns:
            A new (mounted) Terminal widget.
        """

        if (terminal := self._terminal) is not None:
            if terminal.state.buffer.is_blank:
                terminal.finalize()
                await terminal.remove()

        self._terminal_count += 1

        terminal_width, terminal_height = self.get_terminal_dimensions()
        terminal = ShellTerminal(
            f"terminal #{self._terminal_count}",
            id=f"shell-terminal-{self._terminal_count}",
            size=(terminal_width, terminal_height),
            get_terminal_dimensions=self.get_terminal_dimensions,
        )

        terminal.display = False
        terminal = await self.post(terminal)
        self.add_focusable_terminal(terminal)
        self.refresh_bindings()
        return terminal

    def get_terminal_dimensions(self) -> tuple[int, int]:
        """Get the default dimensions of new terminals.

        Returns:
            Tuple of (WIDTH, HEIGHT)
        """
        terminal_width = max(
            16,
            (self.window.size.width - 2 - self.window.styles.scrollbar_size_vertical),
        )
        terminal_height = max(8, self.window.scrollable_content_region.height)
        return terminal_width, terminal_height

    @property
    def shell(self) -> Shell:
        """A Shell instance."""

        if self._shell is None or self._shell.is_finished:
            shell_command = self.app.settings.shell.command
            shell_start = self.app.settings.shell.command_start
            shell_directory = self.working_directory
            self._shell = Shell(
                self, shell_directory, shell=shell_command, start=shell_start
            )
            self._shell.start()
        return self._shell

    async def post_shell(self, command: str) -> None:
        """Post a command to the shell.

        Args:
            command: Command to execute.
        """
        if command.strip():
            self._shell_count += 1
            width, height = self.get_terminal_dimensions()
            await self.shell.send(command, width, height)

    def move_cursor(self, direction) -> None:
        self.navigation.move(direction)
        self.refresh_block_cursor()

    def action_cursor_up(self) -> None:
        self.move_cursor(UpCursor())

    def action_cursor_down(self) -> None:
        self.move_cursor(DownCursor())

    @work
    async def action_cancel(self) -> None:
        if monotonic() - self._last_escape_time < 3:
            if (agent := self.agent) is not None:
                self.flash("Cancelling agent turn…")
                self.activity = "Cancelling…"
                if self._loading is not None and self._loading.is_attached:
                    self._loading.update("Cancelling…")
                self.post_message(
                    messages.SessionUpdate(state="busy", summary="Cancelling")
                )
                if await agent.cancel():
                    self.flash("Turn cancelled", style="success")
                else:
                    self.flash("Agent declined to cancel. Please wait.", style="error")
            self._last_escape_time = 0.0
        else:
            self.flash("Press [b]esc[/] again to cancel agent's turn")
            self._last_escape_time = monotonic()

    def focus_prompt(self, reset_cursor: bool = True, scroll_end: bool = True) -> None:
        """Focus the prompt input.

        Args:
            reset_cursor: Reset the block cursor.
            scroll_end: Scroll t the end of the content.
        """
        if reset_cursor:
            self.navigation.index = -1
            self.cursor.visible = False
        if scroll_end:
            self.jump_to_latest()
        self.prompt.focus()

    def jump_to_latest(self) -> None:
        from toad.widgets.transcript_history import TranscriptHistory

        for history in self.query(TranscriptHistory):
            if history.has_newer:
                history.request_latest()
        self.window.anchor()
        self.transcript.request()

    async def action_select_block(self) -> None:
        if (block := self.cursor_block_child) is None:
            return

        menu_options = [
            MenuItem("[u]C[/]opy to clipboard", "copy_to_clipboard", "c"),
            MenuItem("Co[u]p[/u]y to prompt", "copy_to_prompt", "p"),
            MenuItem("Open as S[u]V[/]G", "export_to_svg", "v"),
        ]

        if block.allow_maximize:
            menu_options.append(MenuItem("[u]M[/u]aximize", "maximize_block", "m"))

        menu_options.extend(block.get_block_menu())
        menu = Menu(block, menu_options)

        menu.offset = Offset(1, block.region.offset.y)
        await self.mount(menu)
        menu.focus()

    def action_copy_to_clipboard(self) -> None:
        block = self.cursor_block_child
        if block is not None and (text := block.get_clipboard_text()):
            self.app.copy_to_clipboard(text)
            self.flash("Copied to clipboard")

    def action_copy_to_prompt(self) -> None:
        block = self.cursor_block_child
        if block is not None and (text := block.get_prompt_text()):
            self.prompt.append(text)
            self.flash("Copied to prompt")
            self.focus_prompt()

    def action_maximize_block(self) -> None:
        if (block := self.cursor_block_child) is not None:
            self.screen.maximize(block, container=False)
            block.focus()

    def action_export_to_svg(self) -> None:
        block = self.cursor_block_child
        if block is None:
            return
        import platformdirs
        from textual._compositor import Compositor
        from textual._files import generate_datetime_filename

        width, height = block.outer_size
        compositor = Compositor()
        compositor.reflow(block, block.outer_size)
        render = compositor.render_full_update()

        import io
        import os.path

        from rich.console import Console

        console = Console(
            width=width,
            height=height,
            file=io.StringIO(),
            force_terminal=True,
            color_system="truecolor",
            record=True,
            legacy_windows=False,
            safe_box=False,
        )
        console.print(render)
        path = platformdirs.user_pictures_dir()
        svg_filename = generate_datetime_filename("Toad", ".svg", None)
        svg_path = os.path.expanduser(os.path.join(path, svg_filename))
        console.save_svg(svg_path)
        import webbrowser

        webbrowser.open(f"file:///{svg_path}")

    async def action_mode_switcher(self) -> None:
        self.prompt.mode_switcher.focus()

    def refresh_block_cursor(self) -> None:
        if (cursor_block := self.cursor_block_child) is not None:
            self.window.focus()
            self.cursor.visible = True
            self.cursor.follow(cursor_block)
            self.call_after_refresh(
                self.window.scroll_to_center, cursor_block, immediate=True
            )
        else:
            self.cursor.visible = False
            self.window.anchor()
            self.cursor.follow(None)
            self.prompt.focus()
        self.refresh_bindings()

    async def slash_command(self, text: str) -> bool:
        """Resolve local declarations before forwarding advertised commands."""
        name, _, arguments = text.partition(" ")
        commands = {command.command: command for command in CommandCatalog(self.agent_slash_commands, self.command_target_context()).commands}
        command = commands.get(name)
        if command is None:
            from toad.thread_actions import ThreadAction
            try:
                member = SlashCommand.decode(name.removeprefix("/"))
            except ValueError:
                try:
                    ThreadAction.decode(name.removeprefix("/"))
                except ValueError:
                    return False
            else:
                if not issubclass(member, LocalCommand):
                    return False
            self.flash("Action is not available for the current target", style="error")
            return True
        if isinstance(command, AgentAdvertisedCommand):
            return False
        try:
            return await command.parse_arguments(arguments).apply(self)
        except (OSError, ValueError) as error:
            self.flash(str(error), style="error")
            return True


class ConversationCommsConsumer(MroDispatch):
    def __init__(self, conversation, message):
        self.conversation = conversation
        self.message = message

    @handles(CursorPresentation)
    async def cursor_presentation(self, update):
        self.conversation.on_private_native_cursor_update(self.message)

    @handles(QueuePresentation)
    async def queue_presentation(self, update):
        await self.conversation.on_queue_view_update(self.message)

    @handles(InputStartedUpdate)
    async def input_started(self, update):
        await self.conversation.on_input_started(self.message)

    @handles(InputFailedUpdate)
    async def input_failed(self, update):
        self.conversation.on_input_failed(self.message)

    @handles(TranscriptChangedUpdate)
    async def transcript_changed(self, update):
        self.conversation.transcript.changed(update.cursor)

    @handles(TurnStartedUpdate)
    async def turn_started(self, update: TurnStartedUpdate):
        await self.conversation.on_turn_started(self.message)

    @handles(TurnSettledUpdate)
    async def turn_settled(self, update: TurnSettledUpdate):
        await self.conversation.on_turn_settled(self.message)

    @handles(GoalChangedUpdate)
    async def goal_changed(self, update: GoalChangedUpdate):
        self.conversation.goal_observation.invalidate()

    @handles(CompactionChangedUpdate)
    async def compaction_changed(self, update: CompactionChangedUpdate):
        await CompactionRenderer(self.conversation).dispatch(update.event)

    @handles(TranscriptSnapshotUpdate)
    async def transcript_snapshot(self, update: TranscriptSnapshotUpdate):
        await self.conversation.transcript.snapshot(update.page)

    @handles(McpClientReceiptUpdate)
    async def mcp_receipt(self, update: McpClientReceiptUpdate):
        await self.conversation.on_mcp_client_status(self.message)

    @handles(CompactionPublishedUpdate)
    async def compaction_published(self, update: CompactionPublishedUpdate):
        self.conversation.transcript.require_checkpoint()



class CompactionRenderer(MroDispatch):
    def __init__(self, conversation):
        self.conversation = conversation

    @handles(comms_events.CompactionStart)
    async def start(self, event):
        view = self.conversation
        view.activity = "Compacting context…"
        view.post_message(
            messages.SessionUpdate(state="busy", summary="Compacting context")
        )

    @handles(comms_events.CompactionProgress)
    async def progress(self, event):
        view = self.conversation
        done, total = event.source_bytes_done, event.source_bytes_total
        if done is not None and total is not None and 0 <= done <= total and total > 0:
            summaries = "summary" if event.chunk_index == 1 else "summaries"
            view.activity = f"Compacting context… {done * 100 // total}% of input processed · {event.chunk_index} {summaries} completed"
            if event.summary_phase == "shrink":
                view.activity += " (last step: summary shrink)"
        else:
            view.activity = (
                f"Compacting context… summary step {event.chunk_index} completed"
            )
        if event.summary_phase == "synthesis":
            view.activity += " · combining summaries"
        view.post_message(messages.SessionUpdate(state="busy", summary=view.activity))

    @handles(comms_events.CompactionEnd)
    async def end(self, event):
        from toad.widgets.agent_response import AgentResponse

        view = self.conversation
        active = view.turns.owner.busy
        view.activity = "Thinking…" if active else ""
        title = "Compaction aborted" if event.aborted else "Context compacted"
        view.post_message(
            messages.SessionUpdate(state="busy" if active else "idle", summary=title)
        )
        summary = compaction_summary(event.publication_summary)
        detail = summary or (
            "Compaction did not complete. Context usage will update after the next measurement."
            if event.aborted
            else "Context estimate unavailable until a new measurement arrives."
        )
        await view.post(
            AgentResponse(f"## {title}\n\n{detail}", category=OtherCategory)
        )
