from __future__ import annotations

from asyncio import Future
import asyncio

from contextlib import suppress
from functools import partial
import hashlib
from itertools import filterfalse
from math import atan2, pi
from operator import attrgetter
from typing import TYPE_CHECKING, Literal
from pathlib import Path
from time import monotonic, time
from urllib.parse import quote
from agent_comms import Goal, GoalExecution, MessageRoute

from typing import Callable, Any

from rich.segment import Segment

from textual import log, on, work
from textual.app import ComposeResult, ScreenStackError, UnknownModeError
from textual import containers
from textual import getters
from textual import events
from textual.actions import SkipAction
from textual.binding import Binding
from textual.content import Content
from textual.geometry import clamp
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static
from textual.widgets.markdown import MarkdownBlock, MarkdownFence
from textual.geometry import Offset, Spacing, Region
from textual.reactive import var
from textual.layouts.grid import GridLayout
from textual.layout import WidgetPlacement
from textual.strip import Strip


from toad import jsonrpc, messages
from toad import paths
from toad.agent_schema import Agent as AgentData
from toad.acp import messages as acp_messages
from toad.app import ToadApp
from toad.acp import protocol as acp_protocol
from toad.answer import Answer
from toad.agent import AgentBase, AgentReady, AgentFail
from toad.format_path import format_path
from toad.directory_watcher import DirectoryWatcher, DirectoryChanged
from toad.history import History
from toad.widgets.flash import Flash
from toad.widgets.menu import Menu
from toad.widgets.note import Note
from toad.widgets.prompt import Prompt
from toad.widgets.terminal import Terminal
from toad.widgets.throbber import Throbber
from toad.widgets.goal_bar import GoalBar, GoalControl
from toad.widgets.input_delivery import InputDeliveryBar, InputDeliveryDetails, empty_delivery
from toad.widgets.user_input import UserInput
from toad.widgets.history_anchor import HistoryWindow
from toad.widgets.message_filter import ALL_CATEGORIES, IN_OUT_CATEGORIES, MESSAGE_CATEGORIES, MessageCategory
from toad.layout import trim_trailing_margin
from toad.shell import Shell, CurrentWorkingDirectoryChanged
from toad.slash_command import SlashCommand
from toad.protocol import BlockProtocol, MenuProtocol, ExpandProtocol
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
    from toad.widgets.terminal import Terminal
    from toad.widgets.agent_response import AgentResponse
    from toad.widgets.agent_thought import AgentThought
    from toad.widgets.terminal_tool import TerminalTool


AGENT_FAIL_HELP = {
    "fail": """\
## Agent failed to run

**The agent failed to start.**

Check that the agent is installed and up-to-date.

Note that some agents require an ACP adapter to be installed to work with Toad.

- Exit the app, and run `toad` again
- Select the agent and hit ENTER
- Click the dropdown, select "Install"
- Click the GO button
- Repeat the process to install an ACP adapter (if required)

Some agents may require you to restart your shell (open a new terminal) after installing.

If that fails, ask for help in [Discussions](https://github.com/batrachianai/toad/discussions)!
""",
    "no_resume": """\
## Agent does not support resume

The agent or ACP adapter does not support resuming sessions.

Try updating to see if support has been added.

- Exit the app, and run `toad` again
- Select the agent and hit ENTER
- Click the dropdown, select "Update" or "Install" again
- Repeat the process to update the ACP adapter (if required)

If that fails, ask for help in [Discussions](https://github.com/batrachianai/toad/discussions)!
""",
}

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


class Loading(Static):
    """Tiny widget to show loading indicator."""

    DEFAULT_CLASSES = "block"
    DEFAULT_CSS = """
    Loading {
        height: auto;        
    }
    """


class ThreadLoading(Static):
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

    def on_mount(self) -> None:
        self.auto_refresh = 1 / 12

    def automatic_refresh(self) -> None:
        if self.is_attached and self.screen is self.app.screen:
            if self in self.screen._compositor.visible_widgets:
                self.refresh(layout=False)

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


class Contents(containers.VerticalGroup, can_focus=False):
    BLANK = True

    def mount(self, *widgets, **kwargs):
        from toad.widgets.message_filter import block_category, keep_live_block

        for widget in widgets:
            widget.set_class(not keep_live_block(widget), "-unrouted")
            if category := block_category(widget):
                widget.add_class(f"-message-{category.value}")
        return super().mount(*widgets, **kwargs)

    def process_layout(
        self, placements: list[WidgetPlacement]
    ) -> list[WidgetPlacement]:
        return trim_trailing_margin(placements)


class ContentsGrid(containers.Grid):
    BLANK = True

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


class Window(HistoryWindow):
    HELP = """\
## Conversation

This is a view of your conversation with the agent.

- **cursor keys** Scroll
- **alt+up / alt+down** Navigate content
- **start typing** Focus the prompt
"""
    BINDING_GROUP_TITLE = "View"
    BINDINGS = [Binding("end", "screen.focus_prompt", "Latest / prompt")]

    def on_mount(self) -> None:
        self.app.settings_changed_signal.subscribe(self, self._settings_changed)
        self._settings_changed(("sidebar.hide", self.app.settings.get("sidebar.hide", bool)))
        self.watch(self, "scroll_y", self.hydrate_visible_tools, init=False)
        self.screen.screen_layout_refresh_signal.subscribe(
            self, lambda _screen: self.hydrate_visible_tools()
        )

    def _settings_changed(self, update: tuple[str, object]) -> None:
        if update[0] == "sidebar.hide":
            top, right, bottom, _ = self.styles.padding
            self.styles.padding = (top, right, bottom, int(bool(update[1])))


class Conversation(containers.Vertical):
    """Holds the agent conversation (input, output, and various controls / information)."""

    BLANK = True
    DEFAULT_CSS = """
    Conversation.-hide-user #contents > .-message-user,
    Conversation.-hide-user #contents > TranscriptHistory > TranscriptPageView > TranscriptFragmentView.-message-user,
    Conversation.-hide-agent #contents > .-message-agent,
    Conversation.-hide-agent #contents > TranscriptHistory > TranscriptPageView > TranscriptFragmentView.-message-agent,
    Conversation.-hide-inbound #contents > .-message-inbound,
    Conversation.-hide-inbound #contents > TranscriptHistory > TranscriptPageView > TranscriptFragmentView.-message-inbound,
    Conversation.-hide-outbound #contents > .-message-outbound,
    Conversation.-hide-outbound #contents > TranscriptHistory > TranscriptPageView > TranscriptFragmentView.-message-outbound,
    Conversation.-hide-thinking #contents > .-message-thinking,
    Conversation.-hide-thinking #contents > TranscriptHistory > TranscriptPageView > TranscriptFragmentView.-message-thinking,
    Conversation.-hide-tool #contents > .-message-tool,
    Conversation.-hide-tool #contents > TranscriptHistory > TranscriptPageView > TranscriptFragmentView.-message-tool,
    Conversation.-hide-other #contents > .-message-other,
    Conversation.-hide-other #contents > TranscriptHistory > TranscriptPageView > TranscriptFragmentView.-message-other {
        display: none;
    }
    Conversation #contents > TranscriptHistory > .filtered-history-results { display: none; }
    Conversation.-filter-active #contents > TranscriptHistory > .filtered-history-results { display: block; }
    """
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
    visible_categories: var[frozenset[MessageCategory]] = var(lambda: ALL_CATEGORIES, init=False)
    cursor_offset = var(-1, init=False)
    project_path = var("")
    working_directory: var[str] = var("")
    _blocks: var[list[MarkdownBlock] | None] = var(None)

    throbber: getters.query_one[Throbber] = getters.query_one("#throbber")
    contents = getters.query_one(Contents)
    window = getters.query_one(Window)
    cursor = getters.query_one(Cursor)
    prompt = getters.query_one(Prompt)
    app = getters.app(ToadApp)

    @property
    def in_out_only(self) -> bool:
        """Compatibility for callers selecting the original two routed kinds."""
        return self.visible_categories == IN_OUT_CATEGORIES

    @in_out_only.setter
    def in_out_only(self, enabled: bool) -> None:
        self.visible_categories = IN_OUT_CATEGORIES if enabled else ALL_CATEGORIES

    def watch_visible_categories(
        self, previous: frozenset[MessageCategory], selected: frozenset[MessageCategory],
    ) -> None:
        window = self.window
        if not hasattr(self, "_filter_scroll_positions"):
            self._filter_scroll_positions = {}
        self._filter_scroll_positions[previous] = (window.scroll_y, window.follows_tail)
        position = self._filter_scroll_positions.get(selected, (window.scroll_y, window.follows_tail))
        self.cursor_offset = -1
        self.screen.clear_selection()
        self.set_class(selected != ALL_CATEGORIES, "-filter-active")
        for category in MESSAGE_CATEGORIES:
            self.set_class(category not in selected, f"-hide-{category.value}")
        for history in tuple(window.histories):
            history.filter_changed()
        revision = window.scroll_revision

        def restore_position():
            if (not self.is_attached or self.visible_categories != selected
                    or window.scroll_revision != revision):
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
    delivering_prompt = var("")
    activity = var("")
    activity_started_at: var[float | None] = var(None)
    sending_queued_prompt = var("")
    current_model: var[Model | None] = var(None)
    thinking_level = var("")
    input_delivery: var[dict] = var(empty_delivery)
    input_delivery_error: var[str] = var("")
    goal_unavailable = var(False)
    goal: var[Goal | None] = var(None)
    goal_execution: var[GoalExecution | None] = var(None)
    turn: var[Literal["agent", "client"] | None] = var(None, bindings=True)
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
        self.agent_slash_commands: list[SlashCommand] = []
        self.terminals: dict[str, TerminalTool] = {}
        self._loading: Loading | None = None
        self._agent_response: AgentResponse | None = None
        self._managed_turn_id: str | None = None
        self._agent_thought: AgentThought | None = None
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
        self._prompt_history_scope = (
            agent_session_id or (f"session-{session_pk}" if session_pk is not None else "")
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

        self._post_lock = asyncio.Lock()
        self._goal_refresh_task: asyncio.Task | None = None
        self._goal_refresh_revision = 0
        self._goal_modal = None
        self._delivery_refresh_task: asyncio.Task | None = None
        self._delivery_refresh_revision = 0
        self._transcript_generation = 0
        self._transcript_dirty = False
        self.displayed_transcript_cursor = None
        self._needs_transcript_checkpoint = False
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

    def shell_complete(self, prefix: str) -> list[str]:
        completes = self.shell_history.complete(prefix)
        return completes

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
            if (session_pk := getattr(self.agent, "session_pk", None)) is not None:
                from toad.db import DB

                await DB().session_update_project(session_pk, str(path))
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

    def watch_turn(self, turn: str) -> None:
        if turn == "client":
            self.post_message(messages.SessionUpdate(state="idle"))
        elif turn == "agent":
            self.post_message(messages.SessionUpdate(state="busy"))

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
        with Window():
            with ContentsGrid():
                with CursorContainer(id="cursor-container"):
                    yield Cursor()
                with Contents(id="contents"):
                    if self._agent_data is not None:
                        yield ThreadLoading()
        yield Flash()
        with containers.Vertical(id="prompt-stack"):
            yield TurnActivity().data_bind(activity=Conversation.activity,
                                           started_at=Conversation.activity_started_at)
            yield Throbber(id="throbber")
            yield InputDeliveryBar().data_bind(
                delivery=Conversation.input_delivery, error=Conversation.input_delivery_error,
            )
            yield GoalBar().data_bind(goal=Conversation.goal, execution=Conversation.goal_execution, unavailable=Conversation.goal_unavailable)
            yield Prompt(complete_callback=self.shell_complete).data_bind(
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
                delivering_prompt=Conversation.delivering_prompt,
                sending_queued_prompt=Conversation.sending_queued_prompt,
                turn=Conversation.turn,
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
            self.cursor_offset = -1
            self.flash("Command interrupted", style="success")

    @on(DirectoryChanged)
    def on_directory_changed(self, event: DirectoryChanged) -> None:
        event.stop()
        if self.turn is None or self.turn == "client":
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
            return True if (self.agent and self.turn == "agent") else None
        if action in {"expand_block", "collapse_block"}:
            if (cursor_block := self.cursor_block) is None:
                return False
            elif isinstance(cursor_block, ExpandProtocol):
                if action == "expand_block":
                    return False if cursor_block.is_block_expanded() else True
                else:
                    return True if cursor_block.is_block_expanded() else False
            return None if action == "expand_block" else False

        return True

    async def action_focus_terminal(self) -> None:
        if self._terminal is not None:
            self._terminal.focus()
        else:
            self.flash("Nothing to focus...", style="error")

    async def action_expand_block(self) -> None:
        if (cursor_block := self.cursor_block) is not None:
            if isinstance(cursor_block, ExpandProtocol):
                cursor_block.expand_block()
                self.refresh_bindings()
                self.call_after_refresh(self.cursor.follow, cursor_block)

    async def action_collapse_block(self) -> None:
        if (cursor_block := self.cursor_block) is not None:
            if isinstance(cursor_block, ExpandProtocol):
                cursor_block.collapse_block()
                self.refresh_bindings()
                self.call_after_refresh(self.cursor.follow, cursor_block)

    async def post_agent_response(self, fragment: str = "", route: MessageRoute | None = None) -> AgentResponse | None:
        """Get or create an agent response widget."""
        from toad.widgets.agent_response import AgentResponse

        async with self._post_lock:
            if self._agent_response is not None and self._agent_response.route != route:
                await self._agent_response.finish_stream()
                self._agent_response = None
            if self._agent_response is None:
                self._agent_response = agent_response = AgentResponse(fragment, route=route)
                await self.post(agent_response, new_block=False)
            else:
                await self._agent_response.append_fragment(fragment)
            return self._agent_response

    async def post_agent_thought(self, thought_fragment: str) -> AgentThought | None:
        """Get or create an agent thought widget."""
        from toad.widgets.agent_thought import AgentThought

        async with self._post_lock:
            if self._agent_thought is None:
                if thought_fragment.strip():
                    self._agent_thought = AgentThought(thought_fragment)
                    await self.post(self._agent_thought, new_block=False)
                    self._agent_thought.loading = False
            else:
                await self._agent_thought.append_fragment(thought_fragment)
            return self._agent_thought

    @property
    def cursor_block(self) -> Widget | None:
        """The block next to the cursor, or `None` if no block cursor."""
        if self.cursor_offset == -1 or not self.contents.displayed_children:
            return None
        try:
            block_widget = self.contents.displayed_children[self.cursor_offset]
        except IndexError:
            return None
        return block_widget

    @property
    def cursor_block_child(self) -> Widget | None:
        if (cursor_block := self.cursor_block) is not None:
            if isinstance(cursor_block, BlockProtocol):
                return cursor_block.get_cursor_block()
        return cursor_block

    def get_cursor_block[BlockType](
        self, block_type: type[BlockType] = Widget
    ) -> BlockType | None:
        """Get the cursor block if it matches a type.

        Args:
            block_type: The expected type.

        Returns:
            The widget next to the cursor, or `None` if the types don't match.
        """
        cursor_block = self.cursor_block_child
        if isinstance(cursor_block, block_type):
            return cursor_block
        return None

    @on(AgentReady)
    async def on_agent_ready(self, message: AgentReady) -> None:
        self.remove_class("-initial-loading")
        await self.query(ThreadLoading).remove()
        if message.reconnected:
            return
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
        self.call_later(self.refresh_goal)
        self.call_later(self.refresh_input_dispositions)
        self._compact_committed_history()
        if self._managed_turn_id is None:
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
        if getattr(self.agent, "server_titles", False):
            return
        await self._apply_session_name(make_session_title(prompt))

    @on(acp_messages.SessionInfoUpdate)
    async def on_session_info_update(
        self, message: acp_messages.SessionInfoUpdate
    ) -> None:
        message.stop()
        if getattr(self.agent, "_coordination_root", None) is not None:
            from toad.db import DB

            self._auto_title_eligible = False
            title = message.title or ""
            if (pk := getattr(self.agent, "session_pk", None)) is not None:
                await DB().session_update_title(pk, title)
            self.post_message(messages.SessionUpdate(name=title))
        else:
            await self.rename_session(message.title or "")

    async def on_unmount(self) -> None:
        if self._directory_watcher is not None:
            self._directory_watcher.stop()
        if self.agent is not None:
            await self.agent.stop()

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
                Content.from_markup(message.details.strip()).stylize("dim"),
            )
        else:
            error = Content.from_markup(message.details.strip()).stylize("$text-error")
        await self.post(Note(error, classes="-error"))

        if message.help == "prompt":
            log_path = getattr(self.agent, "_log_file_path", None)
            if isinstance(log_path, Path):
                from toad.widgets.agent_response import AgentResponse

                link = AgentResponse(
                    f"[Open ACP log]({quote(str(log_path))})", show_divider=False,
                    category=MessageCategory.OTHER,
                )
                link.add_class("-error-log-link")
                await self.post(link)
            return

        from toad.widgets.markdown_note import MarkdownNote

        if message.help in AGENT_FAIL_HELP:
            help = AGENT_FAIL_HELP[message.help]
        else:
            help = AGENT_FAIL_HELP["fail"]

        await self.post(MarkdownNote(help))

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
        methods = getattr(agent, "auth_methods", []) if agent is not None else []
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
                    self.turn == "agent"
                    or self.queued_prompts
                    or getattr(agent, "prompt_in_flight", 0)
                ):
                    await asyncio.sleep(0.1)
                self.prompt.disabled = True
                if getattr(agent, "_coordination_root", None) is None:
                    await self.prune_window(0, 0)
                    self.new_block()
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
            from toad.db import DB
            from textual.geometry import Offset
            from toad.widgets.comms_menu import ContextMenu

            await DB().record_model_usage(self.model_history_scope, event.model_id)
            levels = getattr(self.agent, "thinking_levels", [])
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
                    level=getattr(self.agent, "current_thinking_level", None) or "off",
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
            if event.immediate and not event.shell and self.queue_supported and self.queued_prompts:
                # Keep the queue visible until the exact native input starts.
                self.sending_queued_prompt = self.queued_prompts[0]
                self.send_queued_now()
            return
        self._transcript_generation += 1
        if event.shell:
            if await self.shell.is_busy():
                if self.shell.terminal is not None:
                    self.shell.terminal.focus(scroll_visible=False)
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
            queued = self.turn == "agent" and self.queue_supported and not event.immediate
            if event.immediate and self.queue_supported:
                self.delivering_prompt = text
            if queued:
                self.queued_prompts = [*self.queued_prompts, text]
            else:
                await self.post(UserInput(text))
                self.jump_to_latest()
            # Local feedback precedes persistence and agent metadata work.
            self.prompt_history.current = None
            self.run_worker(self.prompt_history.append(event.body), group="history")
            self.prompt_history_index = 0
            if queued:
                self.send_prompt_to_agent(text, queued=True)
                self.flash("Message queued for after the current response")
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
        if self.agent is not None:
            stop_reason: str | None = None
            uses_turn_events = getattr(self.agent, "uses_turn_events", False)
            if not uses_turn_events:
                self.busy_count += 1
            try:
                if not uses_turn_events:
                    self.turn = "agent"
                if self.queue_supported:
                    stop_reason = await self.agent.send_prompt(
                        prompt,
                        delivery="steer" if immediate else "queue",
                        defer_display=queued,
                    )
                else:
                    stop_reason = await self.agent.send_prompt(prompt)
            except (jsonrpc.APIError, ValueError) as error:
                from toad.widgets.markdown_note import MarkdownNote

                self.turn = "client"

                message = getattr(error, "message", str(error)) or "no details were provided"
                self.activity = ""
                self.activity_started_at = None
                if prompt in self.queued_prompts:
                    remaining = list(self.queued_prompts)
                    remaining.remove(prompt)
                    self.queued_prompts = remaining
                self.prompt.text = "\n\n".join(filter(None, [self.prompt.text, prompt]))

                await self.post(
                    MarkdownNote(
                        INTERNAL_EROR.replace("$ERROR", message),
                        classes="-stop-reason",
                    )
                )
            finally:
                if immediate and self.delivering_prompt == prompt:
                    self.delivering_prompt = ""
                if not uses_turn_events:
                    self.busy_count -= 1
            if not getattr(self.agent, "uses_turn_events", False):
                self.call_later(self.agent_turn_over, stop_reason)

    async def agent_turn_over(self, stop_reason: str | None) -> None:
        """Called when the agent's turn is over.

        Args:
            stop_reason: The stop reason returned from the Agent, or `None`.
        """
        self.turn = "client"
        self._agent_activity_boundary.reset()
        self.activity = ""
        self.activity_started_at = None
        if stop_reason == "end_turn" and self.current_model is not None:
            from toad.db import DB

            await DB().record_model_usage(
                self.model_history_scope, self.current_model.id
            )
        if self._agent_thought is not None and self._agent_thought.loading:
            await self._agent_thought.remove()
        pending_loading, self._loading = self._loading, None
        if pending_loading is not None and pending_loading.is_attached:
            await pending_loading.remove()
        self.new_block()

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

        if self.app.settings.get("notifications.turn_over", bool):
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
        if (cursor_block := self.get_cursor_block()) is not None:
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
        self.new_block()
        await self.post(
            Note(
                Content.styled("Invalid ACP update rejected", "$text-error"),
                classes="-error",
            )
        )

    @on(acp_messages.Update)
    async def on_acp_agent_message(self, message: acp_messages.Update):
        from toad.widgets.agent_response import AgentResponse

        message.stop()
        if self.turn != "agent":
            # Owner notices (including manual compaction) are complete messages,
            # not a live response waiting for a future turn-settled event.
            await self.post(AgentResponse(message.text, route=message.route))
            return
        if self._agent_thought is not None:
            await self._agent_thought.finish_stream()
        self._agent_thought = None
        if self.turn == "agent":
            self.activity = "Writing response…"
            self.post_message(
                messages.SessionUpdate(state="busy", summary="Writing response")
            )
        await self.post_agent_response(message.text, message.route)

    @on(acp_messages.TurnStarted)
    async def on_turn_started(self, message: acp_messages.TurnStarted) -> None:
        message.stop()
        self.activity_started_at = message.started_at
        activity = message.activity_detail if message.activity == "working" else "Thinking…"
        self.activity = activity or "Working…"
        if message.turn_id == self._managed_turn_id:
            return
        self._transcript_generation += 1
        if self._managed_turn_id is None:
            self.busy_count += 1
        self._managed_turn_id = message.turn_id
        self._agent_activity_boundary.reset()
        self.app.open_tabs_changed.publish(None)
        self.new_block()
        self.turn = "agent"
        self.post_message(messages.SessionUpdate(state="busy", summary="Thinking"))

    @on(acp_messages.TurnSettled)
    async def on_turn_settled(self, message: acp_messages.TurnSettled) -> None:
        message.stop()
        if message.turn_id and message.turn_id != self._managed_turn_id:
            return
        self.delivering_prompt = ""
        self.sending_queued_prompt = ""
        self.activity = ""
        self.activity_started_at = None
        self.app.open_tabs_changed.publish(None)
        if message.turn_id is not None:
            if self._managed_turn_id is not None:
                self._managed_turn_id = None
                self.busy_count -= 1
                await self.agent_turn_over("end_turn")
                return
            self.new_block()
            self.turn = "client"
        self.post_message(
            messages.SessionUpdate(state="idle", summary="Ready for review")
        )

    @on(acp_messages.IncomingMessage)
    async def on_incoming_message(self, message: acp_messages.IncomingMessage) -> None:
        from toad.widgets.incoming_message import IncomingMessage

        message.stop()
        if message.sequence <= getattr(self, "_last_incoming_sequence", 0):
            return
        self._last_incoming_sequence = message.sequence
        self.new_block()
        await self.post(IncomingMessage(message.sender, message.text, message.target))

    @on(acp_messages.UserMessage)
    async def on_acp_user_message(self, message: acp_messages.UserMessage):
        self.new_block()
        message.stop()
        await self.post(UserInput(message.text))

    @on(acp_messages.PromptQueueUpdate)
    def on_prompt_queue_update(self, message: acp_messages.PromptQueueUpdate):
        message.stop()
        if not message.queued or message.queued[0] != self.sending_queued_prompt:
            self.sending_queued_prompt = ""
        self.queued_prompts = message.queued
        if message.restored:
            self.prompt.text = "\n\n".join(
                filter(None, [self.prompt.text, *message.restored])
            )
            self.flash("Unprocessed queued messages restored to the composer")

    @on(acp_messages.InputStarted)
    async def on_input_started(self, message: acp_messages.InputStarted):
        message.stop()
        self.new_block()
        if message.text is not None:
            # Consumption is already authoritative even if the full queue
            # snapshot arrives later. Don't flash this input back to "Queued"
            # while its transcript echo is mounting.
            if message.text in self.queued_prompts:
                remaining = list(self.queued_prompts)
                remaining.remove(message.text)
                self.queued_prompts = remaining
            if message.text == self.sending_queued_prompt:
                self.sending_queued_prompt = ""
            await self.post(UserInput(message.text))

    @on(acp_messages.TranscriptSnapshot)
    async def on_transcript_snapshot(self, message: acp_messages.TranscriptSnapshot):
        """Mount saved history once; never feed it through live Markdown streams."""
        from toad.widgets.transcript_history import TranscriptHistory, transcript_blocks
        from toad.widgets.transcript_fragments import prepare_transcript_fragments

        message.stop()
        self._transcript_generation += 1
        generation, agent = self._transcript_generation, self.agent
        window, contents = self.window, self.contents
        scroll_revision = window.scroll_revision
        fragments = await prepare_transcript_fragments(
            message.page.events if message.page is not None else message.events,
            getattr(self.app, "render_processes", None),
        )
        if (not self.is_attached or generation != self._transcript_generation
                or self.agent is not agent or self.window is not window or self.contents is not contents):
            return
        blocks = ([TranscriptHistory(message.page, agent.get_transcript_page, fragments=fragments)]
                  if message.page is not None and agent is not None else
                  [block for fragment in fragments for block in transcript_blocks(
                      fragment.events, fragment=True,
                      show_divider=not fragment.continuation,
                  )])
        self.new_block()
        if blocks:
            # The first replay frame is a latest view, not a remembered scroll
            # position. Anchor before mounting so a large transcript never
            # paints at the top and then walks down after it becomes visible.
            if window.scroll_revision == scroll_revision:
                window.anchor()
            with self.app.batch_update():
                await self.contents.mount(*blocks)
        if message.page is not None:
            self.call_after_refresh(self._record_displayed_transcript, message.page.after)

    def _record_displayed_transcript(self, cursor) -> None:
        self.displayed_transcript_cursor = cursor

    @on(acp_messages.TranscriptChanged)
    def on_transcript_changed(self, message: acp_messages.TranscriptChanged) -> None:
        message.stop()
        self._transcript_dirty = True
        if message.cursor is not None:
            self.call_after_refresh(self._record_displayed_transcript, message.cursor)
        else:
            # Older owners announce commits without a cursor. Display a bounded
            # canonical snapshot before acknowledging their new saved replies.
            self._needs_transcript_checkpoint = True
        self._compact_committed_history()

    @on(acp_messages.CompactionUpdate)
    async def on_acp_compaction_update(self, message: acp_messages.CompactionUpdate) -> None:
        """Display one typed mid-turn notice without settling the current turn."""
        from toad.widgets.agent_response import AgentResponse

        message.stop()
        if message.phase == "progress":
            if message.source_bytes_done is not None and message.source_bytes_total:
                percent = message.source_bytes_done * 100 // message.source_bytes_total
                summaries = "summary" if message.chunk_index == 1 else "summaries"
                self.activity = (
                    f"Compacting context… {percent}% of input processed · "
                    f"{message.chunk_index} {summaries} completed"
                )
                if message.summary_phase == "shrink":
                    self.activity += " (last step: summary shrink)"
            else:
                self.activity = f"Compacting context… summary step {message.chunk_index} completed"
            if message.summary_phase == "synthesis":
                self.activity += " · combining summaries"
            self.post_message(messages.SessionUpdate(state="busy", summary=self.activity))
            return
        if message.phase == "start":
            self.activity = "Compacting context…"
            self.post_message(messages.SessionUpdate(state="busy", summary="Compacting context"))
            return
        active = self.turn == "agent"
        self.activity = "Thinking…" if active else ""
        title = "Context compacted" if message.phase == "end" else "Compaction aborted"
        self.post_message(messages.SessionUpdate(
            state="busy" if active else "idle", summary=title,
        ))
        detail = (
            message.summary or "Context estimate unavailable until a new measurement arrives."
            if message.phase == "end"
            else message.summary
            or "Compaction did not complete. Context usage will update after the next measurement."
        )
        await self.post(AgentResponse(f"## {title}\n\n{detail}", category=MessageCategory.OTHER))

    @work(exclusive=True, group="transcript-window")
    async def _compact_committed_history(self) -> None:
        from agent_comms import UnregisteredThreadError
        from toad.acp.agent import Agent
        from toad.widgets.transcript_history import TranscriptHistory
        from toad.widgets.transcript_fragments import prepare_transcript_fragments
        from toad.widgets.shell_result import ShellResult

        window = self.query_one_optional(Window)
        contents = self.query_one_optional(Contents)
        if (
            window is None or contents is None
            or not self._transcript_dirty
            or not isinstance(self.agent, Agent)
            or not self.agent_ready
            or not self.agent.transcript_ready
            or self._managed_turn_id is not None
            or not window.follows_tail
            or contents.query(ShellResult)
            or (not self._needs_transcript_checkpoint and len(list(contents.query("*"))) < 250)
        ):
            return
        generation = self._transcript_generation
        agent = self.agent
        scroll_revision = window.scroll_revision
        try:
            page = await agent.get_transcript_page()
        except UnregisteredThreadError:
            # Deletion can retire the model before the attachment's final
            # transcript notification has drained. Its view is closing too.
            return
        fragments = await prepare_transcript_fragments(
            page.events, getattr(self.app, "render_processes", None),
        )
        if (not page.events or generation != self._transcript_generation
                or not self.is_attached or self.agent is not agent
                or self.query_one_optional(Window) is not window
                or self.query_one_optional(Contents) is not contents
                or window.scroll_revision != scroll_revision
                or self._managed_turn_id is not None or not window.follows_tail):
            return
        self.new_block()
        self.cursor.follow(None)
        retired = list(contents.children)
        with self.app.batch_update():
            await contents.mount(
                TranscriptHistory(page, agent.get_transcript_page, fragments=fragments), before=0,
            )
            # A new turn can post while mounting awaits. Retire only the captured
            # history, leaving those new blocks after the committed snapshot.
            await contents.remove_children(retired)
        if not window.is_attached or not contents.is_attached:
            return
        self._transcript_dirty = False
        self.call_after_refresh(self._record_displayed_transcript, page.after)
        self._needs_transcript_checkpoint = False
        self.call_after_refresh(window.anchor)

    @on(acp_messages.Thinking)
    async def on_acp_agent_thinking(self, message: acp_messages.Thinking):
        message.stop()
        self.activity = "Thinking…"
        activity = " ".join(message.text.splitlines()).strip() or "Thinking"
        self.post_message(messages.SessionUpdate(state="busy", summary=activity))
        await self.post_agent_thought(message.text)

    @on(acp_messages.RequestPermission)
    async def on_acp_request_permission(self, message: acp_messages.RequestPermission):
        message.stop()
        options = [
            Answer(option["name"], option["optionId"], option["kind"])
            for option in message.options
        ]
        self.request_permissions(
            message.result_future,
            options,
            message.tool_call,
        )
        self.new_block()

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
            self.new_block()

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
        slash_commands: list[SlashCommand] = []
        for available_command in message.commands:
            input = available_command.get("input", {}) or {}
            slash_command = SlashCommand(
                f"/{available_command['name']}",
                available_command["description"],
                hint=input.get("hint"),
            )
            slash_commands.append(slash_command)
        self.agent_slash_commands = slash_commands
        self.update_slash_commands()

    def get_terminal(self, terminal_id: str) -> TerminalTool | None:
        """Get a terminal from its id.

        Args:
            terminal_id: ID of the terminal.

        Returns:
            Terminal instance, or `None` if no terminal was found.
        """
        from toad.widgets.terminal_tool import TerminalTool

        try:
            terminal = self.contents.query_one(f"#{terminal_id}", TerminalTool)
        except NoMatches:
            return None
        if terminal.released:
            return None
        return terminal

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

    @work
    @on(acp_messages.CreateTerminal)
    async def on_acp_create_terminal(self, message: acp_messages.CreateTerminal):
        from toad.widgets.terminal_tool import TerminalTool, Command

        command = Command(
            message.command,
            message.args or [],
            message.env or {},
            message.cwd or str(self.project_path),
        )
        width = self.window.size.width - 5 - self.window.styles.scrollbar_size_vertical
        height = self.window.scrollable_content_region.height - 2

        terminal = TerminalTool(
            command,
            output_byte_limit=message.output_byte_limit,
            id=message.terminal_id,
            minimum_terminal_width=width,
        )
        self.terminals[message.terminal_id] = terminal
        terminal.display = False

        try:
            await terminal.start(width, height)
        except Exception as error:
            log(str(error))
            message.result_future.set_result(False)
            return

        try:
            await self.post(terminal)
        except Exception:
            message.result_future.set_result(False)
        else:
            message.result_future.set_result(True)

    @on(acp_messages.KillTerminal)
    async def on_acp_kill_terminal(self, message: acp_messages.KillTerminal):
        if (terminal := self.get_terminal(message.terminal_id)) is not None:
            terminal.kill()

    @on(acp_messages.GetTerminalState)
    def on_acp_get_terminal_state(self, message: acp_messages.GetTerminalState):
        if (terminal := self.get_terminal(message.terminal_id)) is None:
            message.result_future.set_exception(
                KeyError(f"No terminal with id {message.terminal_id!r}")
            )
        else:
            message.result_future.set_result(terminal.tool_state)

    @on(acp_messages.ReleaseTerminal)
    def on_acp_terminal_release(self, message: acp_messages.ReleaseTerminal):
        if (terminal := self.get_terminal(message.terminal_id)) is not None:
            terminal.kill()
            terminal.release()

    @work
    @on(acp_messages.WaitForTerminalExit)
    async def on_acp_wait_for_terminal_exit(
        self, message: acp_messages.WaitForTerminalExit
    ):
        if (terminal := self.get_terminal(message.terminal_id)) is None:
            message.result_future.set_exception(
                KeyError(f"No terminal with id {message.terminal_id!r}")
            )
        else:
            return_code, signal = await terminal.wait_for_exit()
            message.result_future.set_result((return_code or 0, signal))

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
    async def request_permissions(
        self,
        result_future: Future[Answer],
        options: list[Answer],
        tool_call_update: acp_protocol.ToolCallUpdatePermissionRequest,
    ) -> None:
        kind = tool_call_update.get("kind", None)
        title = tool_call_update.get("title", "") or ""

        contents = tool_call_update.get("content", []) or []
        # If all the content is diffs, we will set kind to "edit" to show the permisisons screen
        for content in contents:
            if content.get("type") != "diff":
                break
        else:
            kind = "edit"

        self.post_message(messages.SessionUpdate(state="asking"))

        if kind == "edit":
            diffs: list[tuple[str, str, str | None, str]] = []

            contents = tool_call_update.get("content", []) or []
            for content in contents:
                match content:
                    case {
                        "type": "diff",
                        "oldText": old_text,
                        "newText": new_text,
                        "path": path,
                    }:
                        diffs.append((path, path, old_text, new_text))

            if diffs:
                from toad.screens.permissions import PermissionsScreen

                self.app.terminal_alert()
                self.app.system_notify(
                    f"{self.agent_title} would like to write files",
                    title="Permissions request",
                    sound="question",
                )
                permissions_screen = PermissionsScreen(
                    options, diffs, agent_name=self.agent_title or "The Agent"
                )
                result = await self.app.push_screen_wait(
                    permissions_screen, mode=self.screen.id
                )
                self.post_message(messages.SessionUpdate(state="busy"))
                self.app.terminal_alert(False)
                result_future.set_result(result)
                return

        from toad.widgets.acp_content import ACPToolCallContent

        def answer_callback(answer: Answer) -> None:
            try:
                result_future.set_result(answer)
            except Exception:
                # I've seen this occur in shutdown with an `InvalidStateError`
                pass

            if not self.prompt.ask_queue:
                self.post_message(messages.SessionUpdate(state="busy"))

        tool_call_content = tool_call_update.get("content", None) or []
        self.ask(
            options,
            title or "",
            (
                partial(ACPToolCallContent, tool_call_content)
                if tool_call_content
                else None
            ),
            answer_callback,
        )
        return

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
    ) -> None:
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

        self.prompt.ask(Ask(title, options, get_content, callback))

    def _build_slash_commands(self) -> list[SlashCommand]:
        slash_commands = [
            SlashCommand(
                "/login", "Connect a provider using the agent's native login UI"
            ),
            SlashCommand(
                "/project", "Change this thread's project directory", "<directory>"
            ),
            SlashCommand(
                "/goal",
                "Set or manage a persistent thread goal",
                "<objective | pause | resume | clear>",
            ),
            SlashCommand(
                "/compact",
                "Compact this thread's model context",
                "<optional summary instructions>",
            ),
            SlashCommand("/model", "Choose this thread's model"),
            SlashCommand("/toad:about", "About Toad"),
            SlashCommand(
                "/toad:clear",
                "Clear conversation window",
                "<optional number of lines to preserve>",
            ),
            SlashCommand(
                "/toad:rename",
                "Give the current session a friendly name",
                "<session name>",
            ),
            SlashCommand(
                "/toad:session-close",
                "Close the current session",
            ),
            SlashCommand(
                "/toad:session-new",
                "Open a new session in the current working directory",
                "<initial prompt or command>",
            ),
            SlashCommand(
                "/toad:testimonial",
                "Tweet a testimonial regarding Toad",
                "<what you think of toad>",
            ),
        ]

        slash_commands.extend(self.agent_slash_commands)
        deduplicated_slash_commands = {
            slash_command.command: slash_command for slash_command in slash_commands
        }
        slash_commands = sorted(
            deduplicated_slash_commands.values(), key=attrgetter("command")
        )
        return slash_commands

    def update_slash_commands(self) -> None:
        """Update slash commands, which may have changed since mounting."""
        self.prompt.slash_commands = self._build_slash_commands()

    async def on_mount(self) -> None:
        self.set_interval(1, self._poll_goal)
        await self.initialize_view()

    async def initialize_view(self) -> None:
        """Initialize the agent view, separate from the framework mount event."""
        self.trap_focus()
        self.watch(self.window, "scroll_y", self._history_scroll_changed, init=False)
        self.prompt.focus()
        self.prompt.slash_commands = self._build_slash_commands()
        self.call_after_refresh(self.post_welcome)
        self.app.settings_changed_signal.subscribe(self, self._settings_changed)
        self.app.open_tabs_changed.subscribe(self, self._coordination_changed)

        self.shell_history.complete.add_words(
            self.app.settings.get("shell.allow_commands", expect_type=str).split()
        )
        self.shell
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

            self.call_after_refresh(start_agent)

        else:
            self.agent_ready = True

        self.update_title()
        self.window.anchor()

    def _history_scroll_changed(self, _position: float) -> None:
        if self._transcript_dirty:
            self.call_after_refresh(self._compact_committed_history)

    def _invalidate_input_dispositions(self) -> None:
        if not self.is_attached or self.agent is None or not hasattr(self.agent, "get_input_delivery"):
            return
        self._delivery_refresh_revision += 1
        if self._delivery_refresh_task is None or self._delivery_refresh_task.done():
            self._delivery_refresh_task = asyncio.create_task(self._read_input_dispositions())

    async def refresh_input_dispositions(self) -> None:
        self._invalidate_input_dispositions()
        if self._delivery_refresh_task is not None:
            await asyncio.shield(self._delivery_refresh_task)

    async def _read_input_dispositions(self) -> None:
        while self.is_attached:
            revision, agent = self._delivery_refresh_revision, self.agent
            if agent is None or not hasattr(agent, "get_input_delivery"):
                return
            try:
                delivery = await agent.get_input_delivery()
            except (OSError, ValueError, RuntimeError, TimeoutError, KeyError) as error:
                if revision != self._delivery_refresh_revision:
                    continue
                self.input_delivery_error = f"Delivery unavailable: {error}"
                return
            if revision != self._delivery_refresh_revision or agent is not self.agent:
                continue
            self.input_delivery = delivery
            self.input_delivery_error = ""
            return

    @property
    def unresolved_inputs(self) -> list[dict]:
        return self.input_delivery["inputs"]

    async def _load_delivery_history(self) -> list[dict]:
        agent = self.agent
        if agent is None:
            raise ValueError("No connected owner.")
        while True:
            revision = self._delivery_refresh_revision
            result = await agent.get_input_delivery(include_history=True)
            if agent is not self.agent:
                raise ValueError("The connected owner changed; inspect delivery again.")
            if revision != self._delivery_refresh_revision:
                continue
            await self.refresh_input_dispositions()
            if agent is not self.agent:
                raise ValueError("The connected owner changed; inspect delivery again.")
            if self.input_delivery_error:
                raise ValueError(self.input_delivery_error)
            # The refresh above adds one revision. A further invalidation means
            # these historical bodies may predate another owner's dismissal.
            if revision + 1 != self._delivery_refresh_revision or any(
                result[key] != self.input_delivery[key]
                for key in ("historicalCount", "dismissedHistoricalCount")
            ):
                continue
            return result["historicalInputs"]

    async def _dismiss_delivery_history(self) -> None:
        agent = self.agent
        if agent is None:
            raise ValueError("No connected owner.")
        await agent.dismiss_historical_inputs()
        if agent is not self.agent:
            raise ValueError("The connected owner changed; inspect delivery again.")
        # Mutate once, then let the sole overview reader reconcile any receipt
        # or newly admitted input that arrived while the action was in flight.
        await self.refresh_input_dispositions()
        if agent is not self.agent:
            raise ValueError("The connected owner changed; inspect delivery again.")
        if self.input_delivery_error:
            raise ValueError(self.input_delivery_error)

    def on_input_dispositions_changed(self, event: acp_messages.InputDispositionsChanged) -> None:
        event.stop()
        self._invalidate_input_dispositions()

    @on(InputDeliveryBar.Inspect)
    async def inspect_input_delivery(self, event: InputDeliveryBar.Inspect) -> None:
        event.stop()
        await self.refresh_input_dispositions()
        details = InputDeliveryDetails(
            log_path=getattr(self.agent, "_log_file_path", None),
            load_history=self._load_delivery_history,
            dismiss_history=self._dismiss_delivery_history,
        )
        # A modal remains a view of the same backend snapshot, including later starts.
        details.delivery = self.input_delivery
        details.error = self.input_delivery_error
        self.app.push_screen(details)
        details.watch(self, "input_delivery", lambda state: setattr(details, "delivery", state))
        details.watch(self, "input_delivery_error", lambda error: setattr(details, "error", error))

    def _poll_goal(self) -> None:
        if not self.is_attached:
            return
        # Only the visible conversation or its own goal modal polls. Hidden tabs
        # do not multiply owner reads; the draft in an edit modal stays local.
        try:
            current = self.app.screen
            visible = (
                current is self.screen
                and self in self.screen._compositor.visible_widgets
            ) or current is self._goal_modal
        except (ScreenStackError, UnknownModeError):
            return
        if visible and (self._goal_refresh_task is None or self._goal_refresh_task.done()):
            self._invalidate_goal_snapshot()

    def _invalidate_goal_snapshot(self) -> None:
        if not self.is_attached or self.agent is None or not hasattr(self.agent, "get_goal_snapshot"):
            return
        self._goal_refresh_revision += 1
        if self._goal_refresh_task is None or self._goal_refresh_task.done():
            self._goal_refresh_task = asyncio.create_task(self._read_goal_snapshot())

    async def refresh_goal(self) -> None:
        self._invalidate_goal_snapshot()
        if self._goal_refresh_task is not None:
            await asyncio.shield(self._goal_refresh_task)

    async def _read_goal_snapshot(self) -> None:
        # All actions and notifications invalidate the same backend projection.
        # A read overtaken by another invalidation is discarded before painting.
        while self.is_attached:
            revision, agent = self._goal_refresh_revision, self.agent
            if agent is None or not hasattr(agent, "get_goal_snapshot"):
                return
            try:
                goal, execution = await agent.get_goal_snapshot()
            except (OSError, ValueError):
                if revision != self._goal_refresh_revision:
                    continue
                self.goal_unavailable = True
                return
            if revision != self._goal_refresh_revision or agent is not self.agent:
                continue
            if self.is_attached:
                self.goal, self.goal_execution = goal, execution
                self.goal_unavailable = False
            return

    def on_goal_snapshot_update(self, event: acp_messages.GoalSnapshotUpdate) -> None:
        self._invalidate_goal_snapshot()

    async def _coordination_changed(self, _update: None) -> None:
        await self.refresh_goal()

    @on(GoalControl.Activated)
    async def on_goal_control(self, event: GoalControl.Activated):
        event.stop()
        if self.goal_unavailable:
            self.flash("Goal state unavailable; waiting for the owner", style="error")
            return
        if event.action == "goal-history" and self.goal is not None:
            from toad.screens.goal_details import GoalDetails

            goal = self.goal
            history = ()
            if self.agent is not None and hasattr(self.agent, "get_goal_history"):
                try:
                    history = await self.agent.get_goal_history(goal.id)
                except (OSError, ValueError) as error:
                    self.flash(str(error), style="error")
                    return
            details = GoalDetails(goal, history=history)
            self._goal_modal = details
            self.app.push_screen(details)
            details.watch(self, "goal", lambda value: setattr(details, "goal", value))
            details.watch(self, "goal_unavailable", lambda value: setattr(details, "unavailable", value))
            details.watch(self, "goal_execution", lambda value: setattr(details, "execution", value))
        elif event.action == "goal-edit":
            from toad.screens.goal_edit import GoalEdit
            from toad.widgets.goal_text import goal_mention_candidates

            goal = self.goal
            if goal is None or self.agent is None or not hasattr(self.agent, "edit_goal"):
                self.flash("Editing requires an agent-comms goal", style="error")
                return

            async def save(text: str) -> None:
                await self.agent.edit_goal(goal, text)
                await self.refresh_goal()

            editor = GoalEdit(goal, goal_mention_candidates(self.app), on_save=save)
            self._goal_modal = editor
            self.app.push_screen(editor)
        elif event.action == "goal-clear":
            await self.change_goal("clear")
        elif event.action == "goal-toggle":
            action = self.goal.toggle_action if self.goal else ""
            if action:
                await self.change_goal(action)
            else:
                self.flash("This goal is completed; set a new goal to continue.")

    async def change_goal(self, action: str, text: str = "") -> None:
        if self.agent is None or not hasattr(self.agent, "update_goal"):
            self.flash("Persistent goals require an agent-comms session", style="error")
            return
        try:
            # Goal state only governs auto-continuation. Changing it must not
            # interrupt work already in progress; the running turn finishes and
            # then scheduling honours the new state.
            await self.agent.update_goal(action, text)
            await self.refresh_goal()
            self.prompt.focus()
        except (OSError, ValueError) as error:
            self.flash(str(error), style="error")

    @work(group="context-compaction")
    async def compact_context(self, instructions: str | None) -> None:
        """Keep processing owner notifications while compaction is in flight."""
        from toad.widgets.agent_response import AgentResponse

        try:
            self.window.anchor()
            self.flash("Compaction requested")
            result = await self.agent.compact_context(instructions)
            if not result.get("ok"):
                await self.post(AgentResponse(
                    "## Compaction failed\n\n" + str(result.get("error") or "No result returned"),
                    category=MessageCategory.OTHER,
                ))
            else:
                self.flash("Context compacted", style="success")
        except (OSError, ValueError, jsonrpc.JSONRPCError) as error:
            await self.post(AgentResponse(f"## Compaction failed\n\n{error}", category=MessageCategory.OTHER))
        finally:
            self._compacting = False

    def open_queue_menu(self) -> None:
        """Offer edit/remove for prompts waiting to be delivered."""
        if not self.queued_prompts:
            return
        from textual.geometry import Offset

        from toad.widgets.comms_menu import ContextMenu

        items: list[tuple[str, str]] = []
        for index, text in enumerate(self.queued_prompts):
            label = " ".join(text.split())[:44]
            items.append((f"edit:{index}", f"✎ {label}"))
            items.append((f"remove:{index}", f"✕ {label}"))
        items.append(("clear", "Clear all queued"))
        anchor = self.prompt.query_one(".queue-summary")
        menu_width = max(len(label) for _, label in items) + 4
        self.app.push_screen(
            ContextMenu(
                Offset(max(0, anchor.region.right - menu_width), anchor.region.bottom),
                "Queued messages",
                items,
            ),
            self._on_queue_choice,
        )

    def _on_queue_choice(self, action: str | None) -> None:
        if not action:
            return
        if action == "clear":
            self.replace_queued([])
            return
        kind, _, raw_index = action.partition(":")
        try:
            index = int(raw_index)
        except ValueError:
            return
        if not 0 <= index < len(self.queued_prompts):
            return
        remaining = list(self.queued_prompts)
        text = remaining.pop(index)
        if kind == "edit":
            self.prompt.text = text
            self.prompt.focus()
        self.replace_queued(remaining)

    @work
    async def replace_queued(self, prompts: list[str]) -> None:
        """Clear prompts awaiting delivery and re-queue the ones kept."""
        queued = list(prompts)
        if self.agent is not None and hasattr(self.agent, "clear_queue"):
            try:
                await self.agent.clear_queue()
            except (OSError, ValueError, jsonrpc.APIError):
                self.flash("Could not reach the agent to update its queue", style="error")
                return
        for text in queued:
            self.send_prompt_to_agent(text, queued=True)
        self.queued_prompts = queued
        self.flash("Cleared queued messages" if not queued else "Updated queued messages")

    def _settings_changed(self, setting_item: tuple[str, str]) -> None:
        key, value = setting_item
        if key == "shell.allow_commands":
            self.shell_history.complete.add_words(value.split())

    @work
    async def post_welcome(self) -> None:
        """Post any welcome content."""

    def watch_agent(self, agent: AgentBase | None) -> None:
        if agent is None:
            self.agent_info = Content.styled("shell")
        else:
            self.agent_info = agent.get_info()
            self.agent_ready = False
        self.update_title()

    @work
    async def watch_agent_ready(self, ready: bool) -> None:
        with suppress(asyncio.TimeoutError):
            async with asyncio.timeout(2.0):
                await self.shell.wait_for_ready()
        if ready:
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

        contents = self.contents
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

        if widget in contents.displayed_children:
            self.cursor_offset = contents.displayed_children.index(widget)
            self.refresh_block_cursor()
            return
        for parent in widget.ancestors:
            if not isinstance(parent, Widget):
                break
            if (
                parent is self or parent is contents
            ) and widget in contents.displayed_children:
                self.cursor_offset = contents.displayed_children.index(widget)
                self.refresh_block_cursor()
                break
            if (
                isinstance(parent, BlockProtocol)
                and parent in contents.displayed_children
            ):
                self.cursor_offset = contents.displayed_children.index(parent)
                parent.block_select(widget)
                self.refresh_block_cursor()
                break
            widget = parent

    def new_block(self) -> None:
        """Start a new block for agent response."""
        for block in (self._agent_thought, self._agent_response):
            if block is not None:
                self.call_later(block.finish_stream)
        self._agent_thought = None
        self._agent_response = None

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
            self.new_block()
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
            low_mark = self.app.settings.get("ui.prune_low_mark", int)
            high_mark = low_mark + self.app.settings.get("ui.prune_excess", int)
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

        self.cursor_offset = -1
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
            shell_command = self.app.settings.get(
                "shell.command",
                str,
                expand=False,
            )
            shell_start = self.app.settings.get(
                "shell.command_start",
                str,
                expand=False,
            )
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
        from toad.widgets.shell_result import ShellResult

        if command.strip():
            self._shell_count += 1
            await self.post(ShellResult(command))
            width, height = self.get_terminal_dimensions()
            await self.shell.send(command, width, height)

    def action_cursor_up(self) -> None:
        if not self.contents.displayed_children or self.cursor_offset == 0:
            # No children
            return
        if self.cursor_offset == -1:
            # Start cursor at end
            self.cursor_offset = len(self.contents.displayed_children) - 1
            cursor_block = self.cursor_block
            if isinstance(cursor_block, BlockProtocol):
                cursor_block.block_cursor_clear()
                cursor_block.block_cursor_up()
        else:
            cursor_block = self.cursor_block
            if isinstance(cursor_block, BlockProtocol):
                if cursor_block.block_cursor_up() is None:
                    self.cursor_offset -= 1
                    cursor_block = self.cursor_block
                    if isinstance(cursor_block, BlockProtocol):
                        cursor_block.block_cursor_clear()
                        cursor_block.block_cursor_up()
            else:
                # Move cursor up
                self.cursor_offset -= 1
                cursor_block = self.cursor_block
                if isinstance(cursor_block, BlockProtocol):
                    cursor_block.block_cursor_clear()
                    cursor_block.block_cursor_up()
        self.refresh_block_cursor()

    def action_cursor_down(self) -> None:
        if not self.contents.displayed_children or self.cursor_offset == -1:
            # No children, or no cursor
            return

        cursor_block = self.cursor_block
        if isinstance(cursor_block, BlockProtocol):
            if cursor_block.block_cursor_down() is None:
                self.cursor_offset += 1
                if self.cursor_offset >= len(self.contents.displayed_children):
                    self.cursor_offset = -1
                    self.refresh_block_cursor()
                    return
                cursor_block = self.cursor_block
                if isinstance(cursor_block, BlockProtocol):
                    cursor_block.block_cursor_clear()
                    cursor_block.block_cursor_down()
        else:
            self.cursor_offset += 1
            if self.cursor_offset >= len(self.contents.displayed_children):
                self.cursor_offset = -1
                self.refresh_block_cursor()
                return
            cursor_block = self.cursor_block
            if isinstance(cursor_block, BlockProtocol):
                cursor_block.block_cursor_clear()
                cursor_block.block_cursor_down()
        self.refresh_block_cursor()

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
            self.cursor_offset = -1
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
        self._compact_committed_history()

    async def action_select_block(self) -> None:
        if (block := self.get_cursor_block(Widget)) is None:
            return

        menu_options = [
            MenuItem("[u]C[/]opy to clipboard", "copy_to_clipboard", "c"),
            MenuItem("Co[u]p[/u]y to prompt", "copy_to_prompt", "p"),
            MenuItem("Open as S[u]V[/]G", "export_to_svg", "v"),
        ]

        print(repr(block))
        if block.allow_maximize:
            menu_options.append(MenuItem("[u]M[/u]aximize", "maximize_block", "m"))

        if isinstance(block, MenuProtocol):
            menu_options.extend(block.get_block_menu())
            menu = Menu(block, menu_options)
        else:
            menu = Menu(block, menu_options)

        menu.offset = Offset(1, block.region.offset.y)
        await self.mount(menu)
        menu.focus()

    def action_copy_to_clipboard(self) -> None:
        block = self.get_cursor_block()
        if isinstance(block, MenuProtocol):
            text = block.get_block_content("clipboard")
        elif isinstance(block, MarkdownFence):
            text = block._content.plain
        elif isinstance(block, MarkdownBlock):
            text = block.source
        else:
            return
        if text:
            self.app.copy_to_clipboard(text)
            self.flash("Copied to clipboard")

    def action_copy_to_prompt(self) -> None:
        block = self.get_cursor_block()
        if isinstance(block, MenuProtocol):
            text = block.get_block_content("prompt")
        elif isinstance(block, MarkdownFence):
            # Copy to prompt leaves MD formatting
            text = block.source
        elif isinstance(block, MarkdownBlock):
            text = block.source
        else:
            return

        if text:
            self.prompt.append(text)
            self.flash("Copied to prompt")
            self.focus_prompt()

    def action_maximize_block(self) -> None:
        if (block := self.get_cursor_block()) is not None:
            self.screen.maximize(block, container=False)
            block.focus()

    def action_export_to_svg(self) -> None:
        block = self.get_cursor_block()
        if block is None:
            return
        import platformdirs
        from textual._compositor import Compositor
        from textual._files import generate_datetime_filename

        width, height = block.outer_size
        compositor = Compositor()
        compositor.reflow(block, block.outer_size)
        render = compositor.render_full_update()

        from rich.console import Console
        import io
        import os.path

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
        """Give Toad the opertunity to process slash commands.

        Args:
            text: The prompt, including the slash in the first position.

        Returns:
            `True` if Toad has processed the slash command, `False` if it should
                be forwarded to the agent.
        """
        command, _, parameters = text[1:].partition(" ")
        if command == "login":
            self.action_provider_login()
            return True
        elif command == "project":
            if not parameters.strip():
                self.flash(Content(f"Project: {self.project_path}"))
            elif self.agent is None or not hasattr(self.agent, "update_project"):
                self.flash(
                    "Project changes require an agent-comms session", style="error"
                )
            else:
                try:
                    path = parameters.strip()
                    if path.startswith(("'", '"')):
                        import shlex

                        values = shlex.split(path)
                        if len(values) != 1:
                            raise ValueError("Expected one project directory")
                        path = values[0]
                    project = await self.agent.update_project(path)
                    self.flash(
                        Content(f"Project changed to {project}"), style="success"
                    )
                except (OSError, ValueError) as error:
                    self.flash(str(error), style="error")
            return True
        elif command == "goal":
            parameter = parameters.strip()
            actions = {
                "pause": "paused", "resume": "active", "retry": "retry", "clear": "clear"
            }
            if parameter in actions:
                await self.change_goal(actions[parameter])
            elif parameter:
                await self.change_goal("set", parameter)
            else:
                await self.refresh_goal()
                self.flash(
                    "Use /goal <objective> to set or edit; pause, resume, retry, or clear to manage it."
                )
            return True
        elif command == "compact":
            if self._compacting:
                self.flash("Context compaction is already running")
            elif self.turn == "agent":
                self.flash("Wait for the current response before compacting", style="error")
            elif self.agent is None or not hasattr(self.agent, "compact_context"):
                self.flash("This agent does not support context compaction", style="error")
            else:
                self._compacting = True
                self.compact_context(parameters.strip() or None)
            return True
        elif command == "model":
            if self.models:
                self.prompt.model_switcher.focus()
            else:
                self.flash("This agent has no model selector", style="error")
            return True
        elif command == "toad:about":
            from toad import about
            from toad.widgets.markdown_note import MarkdownNote

            app = self.app
            about_md = about.render(app)
            await self.post(MarkdownNote(about_md, classes="about"))
            self.app.copy_to_clipboard(about_md)
            self.notify(
                "A copy of /about:toad has been placed in your clipboard",
                title="/toad:about",
            )
            return True
        elif command == "toad:clear":
            try:
                line_count = max(0, int(parameters) if parameters.strip() else 0)
            except ValueError:
                self.notify(
                    "Unable to clear—a number was expected",
                    title="/toad:clear",
                    severity="error",
                )
                return True
            await self.prune_window(line_count, line_count)
            return True
        elif command == "toad:rename":
            name = parameters.strip()
            if not name:
                self.notify(
                    "Expected a name for the session.\n"
                    'For example: "add comments to blog"',
                    title="/toad:rename",
                    severity="error",
                )
                return True
            await self.rename_session(name)
            self.flash(f"Renamed session to [b]'{name}'", style="success")
            return True
        elif command == "toad:session-close":
            if self.turn == "agent" and self.agent is not None:
                await self.agent.cancel()
            if self.screen.id is not None:
                self.post_message(messages.SessionClose(self.screen.id))
                return True
        elif command == "toad:session-new":
            if self._agent_data is not None:
                self.post_message(
                    messages.SessionNew(
                        self.working_directory,
                        self._agent_data["identity"],
                        parameters.strip(),
                    )
                )
                return True
        elif command == "toad:testimonial":
            if self.agent_title is not None:
                default_testimonial = (
                    f"I'm running {self.agent_title} in the terminal with Toad."
                )
            else:
                default_testimonial = (
                    "Try Toad, the universal interface for AI in your terminal"
                )

            testimonial = parameters or default_testimonial
            from toad.twitter import open_tweet_intent

            open_tweet_intent(
                testimonial,
                url="https://github.com/textualize/toad",
                via="willmcgugan",
                hashtags=["ai"],
            )
            return True

        return False
