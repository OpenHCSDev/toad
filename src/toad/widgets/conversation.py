from __future__ import annotations

from toad.conversation_submission import ConversationSubmissions
from toad.live_output import LiveOutput, ThoughtStream
from toad.transcript_publication import TranscriptPresentation
from toad.goal_interaction import GoalSession
from toad.widgets.message_filter import OtherCategory

from toad.settings import PreferenceChange
from toad.preferences import SidebarSettings, ShellSettings

import asyncio
from abc import abstractmethod
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
    PromptCancelledUpdate,
    McpClientReceiptUpdate,
    PendingQueueProjection,
    QueueProjection,
    TranscriptChangedUpdate,
    TranscriptSnapshotUpdate,
    TurnChangedUpdate,
)
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
from textual.geometry import Offset, Region
from textual.layout import WidgetPlacement
from textual.layouts.grid import GridLayout
from textual.reactive import var
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static
from textual.widgets.markdown import MarkdownBlock

from toad import jsonrpc, messages, paths
from toad.acp import messages as acp_messages
from acp import schema as acp_protocol
from toad.acp.status import StopReason, EndTurnStopReason
from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation
from toad.agent import AgentBase, AgentFail, AgentReady
from toad.agent_schema import AgentDefinition
from toad.answer import Answer
from toad.app import ToadApp
from toad.directory_watcher import DirectoryChanged, DirectoryWatcher
from toad.format_path import format_path
from toad.input_history import InputHistories
from toad.widgets.flash import Flash
from toad.widgets.menu import Menu
from toad.widgets.note import Note
from toad.widgets.prompt import Prompt
from toad.widgets.terminal import Terminal
from toad.widgets.throbber import Throbber, ObservedThrobber
from toad.goal_display import GoalDisplay, NoGoal
from toad.session_observation import GoalObservation, InputDeliveryObservation
from toad.widgets.goal_bar import GoalBar, GoalControl
from toad.widgets.native_history import NativeHistory
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.observed_thread_activity import ObservedThreadActivity
from toad.widgets.session_details import SessionDetails
from toad.private_native_cursor import CursorStatus
from toad.block_navigation import admitted_blocks, ConversationBlock, ContentNavigation, UpCursor, DownCursor
from functools import cached_property
from toad.agent_presentation import AgentAttachmentView
from toad.conversation_turn import TurnOwner, ConversationTurn
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
    from toad.acp.agent import Model
    from acp.schema import SessionMode
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

    @classmethod
    def initial_contents(cls, agent):
        """The loading declaration serves first composition and source rebinding."""
        return (cls(),) if agent is not None else ()

    DEFAULT_CSS = """
    ThreadLoading {
        width: 1fr;
        height: auto;
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

    def __init__(self, turns: ConversationTurn):
        super().__init__()
        self.turns = turns

    @property
    def owner(self) -> TurnOwner:
        return self.turns.owner

    def on_mount(self) -> None:
        self.sync()

    def sync(self) -> None:
        owner = self.owner
        self.visible = bool(owner.activity)
        self.auto_refresh = 1 if owner.activity and owner.started_at is not None else None
        self.refresh()

    def render(self) -> Content:
        text = " ".join(self.owner.activity.splitlines())
        if self.owner.started_at is not None:
            elapsed = max(0, int(time() - self.owner.started_at))
            text += f" · {elapsed // 60}:{elapsed % 60:02d} elapsed"
        return Content(text)


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
    """Paint navigation over content geometry without authoring document extent."""

    COMPONENT_CLASSES = {"cursor--selected", "cursor--selected-blink"}
    blink = var(False)

    def on_mount(self) -> None:
        self.set_interval(0.5, self._update_blink)

    def _update_blink(self) -> None:
        blink = (not self.blink
                 if self.query_ancestor(Window).has_focus and self.screen.is_active
                 else False)
        if blink != self.blink:
            self.blink = blink
            self.refresh()

    def render_lines(self, crop: Region) -> list[Strip]:
        rich_style = self.visual_style.rich_style
        strips = [Strip([Segment("▌", rich_style)], cell_length=1)] * crop.height
        if crop.y == 0 and strips:
            strips[0] = Strip([Segment(" ", rich_style)], cell_length=1)
        # Selection belongs to ContentNavigation. The published scene supplies
        # its current position, including nested and lazily replaced bodies.
        visible = self.screen._compositor.visible_widgets
        selected = self.query_ancestor(Conversation).navigation.selected
        if (geometry := visible.get(selected)) is not None:
            region, _clip = geometry
            origin = visible[self][0].y + crop.y
            style = self.get_component_rich_style(
                "cursor--selected-blink" if self.blink else "cursor--selected"
            )
            selected_strip = Strip([Segment("▌", style)], cell_length=1)
            for row in range(max(0, region.y - origin), min(crop.height, region.bottom - origin)):
                strips[row] = selected_strip
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
    BINDINGS = [Binding("end", "focus_prompt", "Latest / prompt")]

    def action_focus_prompt(self) -> None:
        self.query_ancestor(Conversation).focus_prompt()




class ConversationSessionBinding(containers.Vertical):
    """Source-bound state and reusable rich-surface lifecycle shared by conversations."""

    @abstractmethod
    def _turn_changed(self, owner: TurnOwner) -> None:
        """Publish the concrete conversation's changed turn projection."""
        raise NotImplementedError

    busy_count = var(0)


    visible_categories: var[frozenset[type[MessageCategory]]] = var(lambda: all_categories(), init=False)


    project_path = var("")


    working_directory: var[str] = var("")


    _blocks: var[list[MarkdownBlock] | None] = var(None)


    _shell: var[Shell | None] = var(None)




    agent: var[AgentBase | None] = var(None, bindings=True)


    agent_info: var[Content] = var(Content())


    agent_ready: var[bool] = var(False)


    modes: var[dict[str, SessionMode]] = var({}, bindings=True)


    current_mode: var[SessionMode | None] = var(None)


    models: var[dict[str, Model]] = var({}, bindings=True)


    model_history_scope = var("")


    queue_supported = var(False)










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
        agent: AgentDefinition | None = None,
        agent_session_id: str | None = None,
        session_pk: int | None = None,
        session_title: str | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()
        self.turns = ConversationTurn(self._turn_changed, lambda: self.agent.presentation.turns if self.agent else None)
        self._initialize_session(project_path, agent, agent_session_id, session_pk,
                                 session_title, initial_prompt)


    def _initialize_session(self, project_path, agent=None, agent_session_id=None,
                            session_pk=None, session_title=None, initial_prompt=None) -> None:
        project_path = project_path.resolve().absolute()

        self.set_reactive(ConversationSessionBinding.project_path, project_path)
        self.set_reactive(ConversationSessionBinding.working_directory, str(project_path))
        self.agent_slash_commands: list[AgentAdvertisedCommand] = []
        self.output = LiveOutput(self)
        self._loading: Loading | None = None
        self._filter_scroll_positions = {}
        self._mcp_live_note: Note | None = None
        self._private_cursor_sequence = 0
        self.submissions = ConversationSubmissions(self)
        from toad.widgets.agent_activity import AgentActivityBoundary

        self._agent_activity_boundary = AgentActivityBoundary()
        self._last_escape_time = 0.0
        self._agent_data = agent
        self.set_class(agent is not None, "-initial-loading")
        self.set_reactive(
            ConversationSessionBinding.model_history_scope, agent.identity if agent else ""
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
        self.input_histories = InputHistories(
            self.project_data_path, agent_session_id or (
                f"session-{session_pk}" if session_pk is not None else ""
            ),
        )

        self.session_start_time: float | None = None
        self._terminal_count = 0
        self._require_check_prune = False

        self._turn_count = 0
        self._shell_count = 0

        self._directory_changed = False
        self._directory_watcher: DirectoryWatcher | None = None

        self._initial_prompt = initial_prompt
        self._native_agent_started_here = False

        self.goal_observation = GoalObservation(self)
        self.goal_controls = GoalSession(self)
        self.delivery_observation = InputDeliveryObservation(self)
        self.transcript = TranscriptPresentation(self)
        self.tool_expansions: dict[str, bool] = {}


    async def release_native_session(self) -> None:
        """Invalidate all old publications before this rich surface changes source."""
        await self.transcript.close()
        self.goal_controls.close()
        self.output.retire()
        if self._directory_watcher is not None:
            await self._directory_watcher.aclose()
            self._directory_watcher = None
        await self.window.document_viewport.suspend_source()
        await asyncio.gather(self.goal_observation.close(),
                             self.delivery_observation.close())
        self.agent = None
        self._initial_prompt = None
        await self.contents.remove_children()
        self.navigation.index = -1
        self.cursor.refresh()
        self.prompt._ask = None
        self.prompt.ask_queue.clear()
        self._focusable_terminals.clear()

    async def prepare_retained_session(self) -> None:
        """The actual source chooses restoration; a history widget is not an actor."""
        agent = self.agent
        if agent is None:
            self.resume_retained_history()
        elif agent.ready:
            await agent.presentation.restore_saved_history(self)

    def resume_retained_history(self) -> None:
        """The selected view restores its existing non-native pager resources."""
        from toad.widgets.transcript_history import TranscriptHistory

        for history in self.contents.query(TranscriptHistory):
            history.state.resume_if_parked(history)

    async def present_retained_native_session(self) -> None:
        """Bring a returning native source into the atomic first frame."""
        agent = self.agent
        if agent is None or not agent.ready:
            return
        self.refresh_native_projection()
        page, _ = await asyncio.gather(
            agent.get_transcript_page(),
            self.delivery_observation.refresh(),
        )
        if self.agent is not agent:
            return
        await self.transcript.snapshot(page)
        if self.agent is not agent:
            return
        await self.query(ThreadLoading).remove()
        self.remove_class("-initial-loading")

    def refresh_native_projection(self) -> None:
        """Publish bound owner facts and invalidate its existing read resource."""
        agent = self.agent
        if agent is None:
            return
        self.status = agent.context_measurement.status()
        self.turns.bound()
        self.submissions.publish_pending()
        self.goal_observation.invalidate()



    def start_native_session(self) -> None:
        # Source identity must include its filesystem owner before the first
        # saved-history publication, rather than changing after AgentReady.
        if self._directory_watcher is None:
            self._directory_watcher = DirectoryWatcher(self.project_path, self)
            self._directory_watcher.start()
        if self.agent is not None:
            self.agent_ready = self.agent.ready
            return
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
                self._native_agent_started_here = True
                await self.agent.start(self)
                self.post_message(
                    messages.SessionUpdate(
                        self._session_title or "New Session", self.agent_title
                    )
                )

            from toad.screens.workspace import WorkspaceScreen

            screen = self.screen
            if isinstance(screen, WorkspaceScreen):
                screen.frame_presentation.defer(self, start_agent)
            else:
                self.call_after_refresh(start_agent)

        else:
            self.agent_ready = True

    @work
    async def watch_agent_ready(self, ready: bool) -> None:
        presentation = self.transcript
        if presentation.view is not self:
            return
        if ready:
            self.remove_class("-initial-loading")
            await self.query(ThreadLoading).remove()
            if self.transcript is not presentation or presentation.view is not self:
                return
        if ready and self._native_agent_started_here and (agent_data := self._agent_data) is not None:
            welcome = agent_data.welcome
            if welcome is not None:
                from toad.widgets.markdown_note import MarkdownNote

                await self.post(MarkdownNote(welcome))
                if self.transcript is not presentation or presentation.view is not self:
                    return
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
        if ready:
            self._native_agent_started_here = False


from toad.widget_actions import DeclaredWidgetActions
from toad.conversation_actions import ConversationAction


class Conversation(DeclaredWidgetActions, ConversationSessionBinding):
    ACTIONS = ConversationAction
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
            "ctrl+c",
            "interrupt",
            "Interrupt",
            tooltip="Interrupt running command",
        ),
    ]


    throbber: getters.query_one[Throbber] = getters.query_one("#throbber")
    contents = getters.query_one("#contents", Contents)
    window = getters.query_one(Window)
    cursor = getters.query_one(CursorContainer)
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
            return self._agent_data.name
        return None

    @property
    def is_watching_directory(self) -> bool:
        """Is the directory watcher enabled and watching?"""
        if self._directory_watcher is None:
            return False
        return self._directory_watcher.enabled


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
        self.input_histories.bind_project(self.project_data_path)
        if self._directory_watcher is not None:
            await self._directory_watcher.aclose()
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
            if (session_pk := self.agent.session.pk) is not None:
                from toad.db import DB

                await DB().session_update_project(session_pk, path)
        self.update_title()

    def _turn_changed(self, owner: TurnOwner) -> None:
        self._sync_throbber()
        if (activity := self.query_one_optional(TurnActivity)) is not None:
            activity.sync()
        if (prompt := self.query_one_optional(Prompt)) is not None:
            prompt.sync_turn()
        if (details := self.query_one_optional(SessionDetails)) is not None:
            details.sync_turn()
        self.refresh_bindings()

    def make_throbber(self) -> ObservedThrobber:
        return ObservedThrobber(
            lambda: self.busy_count > 0 or self.turns.owner.busy, id="throbber"
        )

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
                yield CursorContainer(id="cursor-container")
                with Contents(id="contents"):
                    yield from ThreadLoading.initial_contents(self._agent_data)
        yield Flash()
        with containers.Vertical(id="prompt-stack"):
            yield TurnActivity(self.turns)
            yield SessionDetails(
                self._read_thread_activity,
                turns=self.turns,
                transcript=self.transcript,
                history=NativeHistory().data_bind(
                    status=Conversation.native_history_status
                ),
                delivery=InputDeliveryBar().data_bind(
                    delivery=Conversation.input_delivery,
                    error=Conversation.input_delivery_error,
                ),
            )
            yield self.make_throbber()
            yield GoalBar(self)
            yield Prompt(turns=self.turns, submissions=self.submissions).data_bind(
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

    @property
    def terminal_action_state(self) -> bool | None:
        return None if self._terminal is None else True

    def focus_terminal(self) -> None:
        if (terminal := self._terminal) is not None:
            terminal.focus()

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
    async def on_observed_thread_activity(
        self, event: ObservedThreadActivity.Changed
    ) -> None:
        event.stop()
        if not event.current:
            return
        if event.presentation is not None:
            from toad.transcript_publication import ObservedSourcePublication
            self.transcript.source_requests.request(ObservedSourcePublication, event.presentation)


    @on(AgentReady)
    async def on_agent_ready(self, message: AgentReady) -> None:
        if not message.reconnected:
            self.session_start_time = monotonic()
            if self.agent is not None:
                content = Content.assemble(self.agent.get_info(), " connected")
                self.flash(content, style="success")
                if self._agent_data is not None:
                    self.app.application.usage.publish(
                        "agent-session-begin",
                        agent=self._agent_data.identity,
                    )

        self.agent_ready = True
        self.call_later(self.goal_observation.refresh)
        self.call_later(self.delivery_observation.refresh)
        self.transcript.request()
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
            if (pk := self.agent.session.pk) is not None:
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
            await self._directory_watcher.aclose()
            self._directory_watcher = None
        if self.agent is not None:
            await self.agent.retire_surface(self)

        if self._agent_data is not None and self.session_start_time is not None:
            session_time = monotonic() - self.session_start_time
            await self.app.application.usage.publish(
                "agent-session-end",
                agent=self._agent_data.identity,
                duration=session_time,
                agent_session_fail=self._agent_fail,
                shell_count=self._shell_count,
                turn_count=self._turn_count,
            ).wait()

    @on(AgentFail)
    async def on_agent_fail(self, message: AgentFail) -> None:
        self.remove_class("-initial-loading")
        await self.query(ThreadLoading).remove()
        self.turns.finish_client()
        self.agent_ready = True
        self._agent_fail = True
        self.notify(message.message, title="Agent failure", severity="error", timeout=5)

        if self._agent_data is not None:
            self.app.application.usage.publish(
                "agent-session-error",
                agent=self._agent_data.identity,
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
        from toad.agent_schema import Command
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
                [(method.id, method.name) for method in methods],
            ),
            mode="workspace",
        )
        if not method_id:
            self.prompt.focus()
            return
        method = next(method for method in methods if method.id == method_id)
        try:
            if isinstance(method, acp_protocol.TerminalAuthMethod):
                command = agent.command
                if not command:
                    raise ValueError("This agent has no configured login program")
                arguments = method.args or []
                command = command + (" " + shlex.join(arguments) if arguments else "")
                code = await self.app.push_screen_wait(
                    ActionModal(
                        Command(method.name, command).bind("login"),
                        agent.definition,
                        command,
                        env=method.env or {},
                        cwd=str(self.project_path),
                    ),
                    mode="workspace",
                )
                if code != 0:
                    return
                while (
                    self.turns.owner.busy
                    or self.submissions.queue_projection.items
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
                await agent.session.reconnect()
            else:
                await agent.session.authenticate(method_id)
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
            levels = [choice.value for choice in self.agent.configuration.thinking.choices]
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
                    mode="workspace",
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
                    level=self.agent.configuration.thinking.current or "unavailable",
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
        """Wire views override the same submission boundary."""
        await self.submissions.submit(event)

    async def agent_turn_over(self, stop_reason: type[StopReason] | None) -> None:
        """Called when the agent's turn is over.

        Args:
            stop_reason: The stop reason returned from the Agent, or `None`.
        """
        self.turns.finish_client()
        self._agent_activity_boundary.reset()
        if stop_reason is not None and stop_reason.completed and self.current_model is not None:
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


        if stop_reason is not None:
            await stop_reason.present(self)

        if self.app.settings.notifications.turn_over:
            self.app.terminal_attention.notify(
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
            self.call_after_refresh(self.cursor.refresh)
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

    def _sync_throbber(self) -> None:
        if (throbber := self.query_one_optional("#throbber", ObservedThrobber)) is not None:
            throbber.sync()

    async def watch_busy_count(self, _busy: int) -> None:
        self._sync_throbber()

    @on(acp_messages.UpdateStatusLine)
    async def on_update_status_line(self, message: acp_messages.UpdateStatusLine):
        # The shared widget can receive a queued status message after its
        # source changes. The selected Agent owns the measured value.
        if self.agent is not None:
            self.status = self.agent.context_measurement.status()

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
            or (self.agent.current_turn.managed_id if self.agent else None)
            != message.update.turn_id
            or self.turns.managed_id is None
            or message.update.turn_id != self.turns.managed_id
            or (agent_session is not None and message.session_id != agent_session)
        ):
            # Late or forged: the projection dies with its turn and is never
            # shown outside the active-turn lifetime.
            return
        if self._mcp_live_note is not None:
            return  # The package emits at most one receipt per turn.
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
        message.stop()
        if message.agent is not self.agent:
            return
        if self.turns.owner.busy:
            self.turns.describe("Writing response…")
        await self.output.append(message.stream, message.text)

    async def on_turn_changed(self, message: acp_messages.CommsUpdated) -> None:
        if not self.turns.changed(message):
            return
        self.app.open_tabs_changed.publish(None)
        if self.turns.owner.busy:
            self.transcript.invalidate()
            return
        await self._clear_mcp_live()
        self._agent_activity_boundary.reset()
        await self.output.settle()
        self.transcript.retry()

    async def on_queue_view_update(self, message: acp_messages.CommsUpdated) -> None:
        if (
            self.agent is None
            or message.agent is not self.agent
            or message.session_id != self.agent.session_id
        ):
            return
        async with self.window.preserve_history(None):
            for started in message.update.starts:
                if (
                    message.agent is not self.agent
                    or message.session_id != self.agent.session_id
                ):
                    return
                await self.present_started_input(started)
            self.submissions.publish_pending()

    async def on_input_started(self, message: acp_messages.CommsUpdated):
        if (
            self.agent is None
            or message.agent is not self.agent
            or message.session_id != self.agent.session_id
        ):
            return
        if message.update.text is not None:
            async with self.window.preserve_history(None):
                await self.present_started_input(message.update)
                self.submissions.publish_pending()

    async def present_started_input(self, started) -> None:
        from toad.widgets.committed_presentation import StartedInputClaim

        self.output.boundary()
        await self.post(UserInput(started.text, claim=StartedInputClaim(started)))
        self.submissions.native_input_presented(started)

    def on_input_failed(self, message: acp_messages.CommsUpdated) -> None:
        """Only a locally failed request may recover its own draft text."""
        if not self.submissions.accepts_failure(message):
            return
        if not message.recover_draft:
            # Server notices (including unstarted queued/restored inputs) are
            # read-only evidence, not permission to change the local composer.
            self.flash(
                f"{message.update.failure.title}: {message.update.failure.description}\n{message.update.failure.input_disposition}\n{message.update.failure.action}",
                style="error",
            )
            return
        self.submissions.restore_draft(message.update.text)

        self.flash(
            f"{message.update.failure.title}; draft restored: {message.update.failure.description}\n{message.update.failure.input_disposition}\n{message.update.failure.action}",
            style="error",
        )

    async def on_transcript_coverage(self, message) -> None:
        message.stop()
        await self.transcript.covered(message)

    def on_transcript_source_work_finished(self, message) -> None:
        message.stop()
        self.transcript.source_work_finished(message.history)

    def on_worker_state_changed(self, message) -> None:
        if message.worker is self.transcript.worker and message.worker.is_finished:
            self.transcript.retry()

    @on(acp_messages.Thinking)
    async def on_acp_agent_thinking(self, message: acp_messages.Thinking):
        message.stop()
        self.turns.describe("Thinking…")
        activity = " ".join(message.text.splitlines()).strip() or "Thinking"
        await self.output.append(ThoughtStream(), message.text)

    @on(acp_messages.RequestPermission)
    async def on_acp_request_permission(self, message: acp_messages.RequestPermission):
        message.stop()
        self.request_permissions(message.request)
        self.output.boundary()

    @on(acp_messages.Plan)
    async def on_acp_plan(self, message: acp_messages.Plan):
        from toad.widgets.plan import Plan

        if self.contents.children and isinstance(
            (current_plan := self.contents.children[-1]), Plan
        ):
            current_plan.entries = message.entries
        else:
            await self.post(Plan(message.entries))

    @on(acp_messages.ToolCallUpdate)
    @on(acp_messages.ToolCall)
    async def on_acp_tool_call_update(
        self, message: acp_messages.ToolCall | acp_messages.ToolCallUpdate
    ):
        from toad.widgets.tool_call import ToolCall

        tool_call = message.tool_call
        tool_call.activity(self, tool_call.call.title or 'Using tool')

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
        history = self.input_histories.history(message.history_kind)
        entry = await history.navigate(message.direction, message.body)
        history.present(self.prompt, entry)

    @work
    async def request_permissions(self, request) -> None:
        await request.presentation.present(self, request)

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
        self.app.terminal_attention.notify(notify_message, title=notify_title, sound="question")

        ask = Ask(title, options, get_content, callback)
        self.prompt.ask(ask)
        return ask

    def command_target_context(self):
        from toad.screens.main import MainScreen
        from toad.target_commands import ThreadContext
        nav = self.query_ancestor(MainScreen).navigation_context
        comms = self.app.coordination_access.service
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

        self.input_histories.shell.complete.add_words(
            self.app.settings.shell.allow_commands.split()
        )
        self.start_native_session()
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
        try:
            self.window.anchor()
            self.flash("Compaction requested")
            await self.agent.controller.compact_context(instructions)
            self.flash("Context compacted", style="success")
        except (OSError, ValueError, jsonrpc.JSONRPCError) as error:
            self.notify(str(error), title="Compaction request", severity="error")
            self.transcript.require_checkpoint()

    def open_queue_menu(self) -> None:
        """Remote edits require exact input IDs and backend revision-CAS support."""
        if self.submissions.queue_projection.items:
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
            self.input_histories.shell.complete.add_words(
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
                       else AgentAttachmentView(None, 0))
        self.native_history_status = attachments.cursor
        self._private_cursor_sequence = attachments.cursor_sequence
        self.submissions.reset()
        if (observed := self.query_one_optional(ObservedThreadActivity)) is not None:
            observed.bind(agent.get_thread_presentation if agent is not None else self._read_thread_activity)
        self.turns.bound()
        self.busy_count = 0
        if agent is None:
            self.agent_info = Content.styled("shell")
        else:
            self.agent_info = agent.get_info()
            self.agent_ready = agent.ready
            self.status = agent.context_measurement.status()
            if self.agent_ready:
                self.call_later(self.goal_observation.refresh)
                self.call_later(self.delivery_observation.refresh)
        self.update_title()

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
        from toad.screens.session_view import SessionView

        # A queued history click may arrive after its logical source retired.
        if not self.query_ancestor(SessionView).is_current:
            return
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
            if self.agent is not None and self.agent.transcript_ready:
                # Height pressure is not source evidence. Dropping the source
                # pager or an uncovered wire claim lets a later observation
                # recreate the same record as a new tail arrival.
                if self.contents.virtual_size.height > high_mark:
                    self.transcript.require_checkpoint()
            else:
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
        self.cursor.refresh()
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
    async def cancel_turn(self) -> None:
        if monotonic() - self._last_escape_time < 3:
            if (agent := self.agent) is not None:
                self.flash("Cancelling agent turn…")
                self.turns.describe("Cancelling…")
                if self._loading is not None and self._loading.is_attached:
                    self._loading.update("Cancelling…")
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
            self.cursor.refresh()
        if scroll_end:
            self.jump_to_latest()
        self.prompt.focus()

    def jump_to_latest(self) -> None:
        self.window.jump_to_latest()
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

    def refresh_block_cursor(self) -> None:
        self.cursor.refresh()
        if (cursor_block := self.cursor_block_child) is not None:
            # Resolve this navigation event before a later tab/editor event.
            self.screen.set_focus(self.window)
            self.call_after_refresh(
                self.window.scroll_to_center, cursor_block, immediate=True
            )
        else:
            self.window.anchor()
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

    @handles(PromptCancelledUpdate)
    async def prompt_cancelled(self, update):
        from toad.widgets.markdown_note import MarkdownNote
        await self.conversation.post(MarkdownNote(
            f"## Turn cancelled\n\n{update.feedback}", classes="-stop-reason"))

    @handles(TranscriptChangedUpdate)
    async def transcript_changed(self, update):
        self.conversation.transcript.changed(update.cursor)

    @handles(TurnChangedUpdate)
    async def turn_changed(self, update):
        await self.conversation.on_turn_changed(self.message)

    @handles(GoalChangedUpdate)
    async def goal_changed(self, update: GoalChangedUpdate):
        self.conversation.goal_observation.receive(self.message.agent, (update.goal, update.execution))

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

    @handles(comms_events.CompactionSummaryProgress)
    async def selected_summary_progress(self, event):
        view = self.conversation
        if event.text and event.source is not None and event.source.summary_phase != "map":
            from toad.live_output import CompactionStream
            await view.output.append(CompactionStream(event.operation_id), event.text)

    @handles(comms_events.CompactionEnd)
    async def end(self, event):
        view = self.conversation
        from toad.live_output import CompactionStream
        await view.output.finish(CompactionStream)
        # The native entry or original journal outcome owns the retained notice.
        # A terminal event invalidates that source; it does not create a second
        # response with an unrelated native-output retirement claim.
        view.transcript.require_checkpoint()
