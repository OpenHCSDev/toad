from __future__ import annotations
from toad.core import input_events
from toad.core_event_carrier import CoreEventMessage
from toad.widget_view import WorkspaceHosted

from toad.conversation_submission import ConversationSubmissions
from toad.live_output import LiveOutput, ThoughtStream
from toad.transcript_publication import TranscriptPresentation
from toad.goal_interaction import GoalSession

from toad.core.preference_events import PreferenceChanged
from toad.preferences import SETTINGS

import asyncio
from abc import abstractmethod
from contextlib import suppress
from toad.resource_release import AsyncResourceRelease
from itertools import filterfalse

from operator import attrgetter
from pathlib import Path
from time import monotonic, time_ns
from typing import TYPE_CHECKING, Any, Callable, Literal

from agent_comms import agent_events as comms_events
from agent_comms.acp_extension import (
    CompactionChangedUpdate,
    CoordinationChangedUpdate,
    GoalChangedUpdate,
    InputFailedUpdate,
    InputStartedUpdate,
    PromptCancelledUpdate,
    McpClientAcknowledgementUpdate,
    TranscriptChangedUpdate,
    TranscriptSnapshotUpdate,
    TurnChangedUpdate,
)
from agent_comms.goal_presentation import ThreadGoalExecution, IdleGoalExecution
from agent_comms.mro_dispatch import MroDispatch, handles
from rich.segment import Segment
from rich.text import Text as RichText
from textual import containers, events, getters, on, work
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.actions import SkipAction
from textual.app import ComposeResult
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

from toad import messages, paths
from acp.exceptions import RequestError
from toad.widgets.splash_text import SplashText

from toad.core import events as core_events
from toad.widgets.comms_menu import ContextMenu
from toad.core_event_carrier import CoreEventReceiver
from acp import schema as acp_protocol
from toad.acp.agent_session import SessionDisposition
from toad.acp.status import StopReason
from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation
from toad.core.events import AgentFail, AgentReady
from toad.agent import AgentBase
from toad.widgets.terminal_tool import TerminalTool
from toad.agent_schema import AgentDefinition
from toad.answer import Answer
from toad.app import ToadApp
from toad.core.source_events import CurrentWorkingDirectoryChanged, TranscriptCoverage, TranscriptSourceWorkFinished, MessageHandlingRequested
from toad.input_history import InputHistories
from toad.widgets.flash import Flash
from toad.widgets.menu import Menu
from toad.widgets.note import Note
from toad.widgets.prompt import Prompt
from toad.widgets.terminal import Terminal
from toad.widgets.throbber import AboveThrobber, BelowThrobber
from toad.frame_presentation import Animated
from ui_theme.effects import CURSOR_BLINK, Mix
from agent_comms.ui_model.delivery import InputDelivery
from agent_comms.ui_model.goal import GoalDisplay, NoGoal
from toad.session_observation import GoalObservation, InputDeliveryObservation, SessionObservation
from toad.widgets.goal_bar import GoalBar
from toad.widgets.native_history import NativeHistory
from toad.widgets.observed_thread_activity import ObservedThreadActivity, ThreadStatusOwner
from toad.widgets.cli_draft import CliDraft
from toad.widgets.transcript_history import JumpToLatest
from toad.widgets.session_details import SessionDetails
from toad.private_native_cursor import CursorStatus, HiddenCursorStatus
from toad.block_navigation import require_blocks, ConversationBlock, ContentNavigation, UpCursor, DownCursor
from functools import cached_property
from toad.agent_presentation import AgentAttachmentView
from toad.conversation_turn import TurnOwner, ConversationTurn
from toad.shell import Shell
from toad.widgets.history_anchor import HistoryWindow
from toad.widgets.input_delivery import (
    DetailAction,
    InputDeliveryBar,
    InputDeliveryDetails,
)
from toad.widgets.user_input import UserInput
from toad.widgets.message_filter import all_categories, MessageCategory
from toad.layout import trim_trailing_margin
from toad.command_catalog import CommandCatalog
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
    from toad.widgets.question import Ask
    from toad.widgets.terminal import Terminal
    from toad.widgets.transcript_history import LineHistory



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


class ThreadLoading(ConversationBlock, SplashText):
    """The splash while a thread attaches: its label swept into the theme's colours."""

    LABEL = TEXT = "Loading thread and history…"

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

    def on_mount(self) -> None:
        self.play()


class CategorizedMount:
    """Mount blocks in their declared order with the conversation's category selection."""

    def mount(self, *widgets, **kwargs):
        from toad.widgets.message_filter import apply_block_filter

        selected = self.selected_categories
        for widget in require_blocks(widgets):
            apply_block_filter(widget, selected)
        mounted = super().mount(*widgets, **kwargs)
        # Registration is synchronous: establish document order before any
        # new widget's mount task or paint can run. The stable sort preserves
        # order within saved sources and within live output.
        self.sort_children(key=lambda block: block.conversation_order)
        return mounted


class Contents(containers.VerticalGroup, can_focus=False):
    CACHE_SUBTREE_GEOMETRY = True
    BLANK = True

    def line_histories(self):
        """Visit history containers without entering their rich bodies."""
        from toad.widgets.transcript_history import LineHistory

        pending = list(reversed(self.children))
        while pending:
            child = pending.pop()
            if isinstance(child, LineHistory):
                yield child
                pending.extend(reversed(child.children))

    @property
    def line_width(self) -> int:
        """The native width of full-width history rows prepared before mounting."""
        return self.content_size.width

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        return all_categories()

    async def prepare_history(self, history: LineHistory, current: Callable[[], bool], *,
                              window: HistoryWindow) -> None:
        """Supply a laid-out native target before its detached history prepares rows."""
        if not self.line_width:
            await self.wait_for_refresh()
        rows, _limit = window.latest_limits(history.budget)
        await history.prepare_rows(current, window=window, target=self, selected=self.selected_categories,
                                   rows_needed=rows)

    @height_dependency(INDEPENDENT_HEIGHT)
    def process_layout(
        self, placements: list[WidgetPlacement]
    ) -> list[WidgetPlacement]:
        return trim_trailing_margin(placements)


class ConversationContents(CategorizedMount, Contents):
    """Conversation ordering and categories compose with the native row container."""

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        return (self.query_ancestor(Conversation).visible_categories
                if self.is_attached else all_categories())


class ContentsGrid(containers.Grid):
    BLANK = True

    @height_dependency(INDEPENDENT_HEIGHT)
    def pre_layout(self, layout) -> None:
        assert isinstance(layout, GridLayout)
        layout.stretch_height = True


class CursorContainer(Animated[Mix], Static):
    """Paint navigation over content geometry without authoring document extent."""

    COMPONENT_CLASSES = {"cursor--selected"}

    def on_mount(self) -> None:
        self.watch(self.query_ancestor(Window), "has_focus", self.app.colours.clock.refresh)
        self.run_effect(CURSOR_BLINK)

    @property
    def animation_visible(self) -> bool:
        return super().animation_visible and self.query_ancestor(Window).has_focus

    def render_lines(self, crop: Region) -> list[Strip]:
        rich_style = self.visual_style.rich_style
        strips = [Strip([Segment("▌", rich_style)], cell_length=1)] * crop.height
        if crop.y == 0 and strips:
            strips[0] = Strip([Segment(" ", rich_style)], cell_length=1)
        # Selection belongs to ContentNavigation. The published scene supplies
        # its current position, including nested and lazily replaced bodies.
        visible = self.screen._compositor.visible_widgets
        cursor = self.query_ancestor(Conversation).navigation.cursor
        if cursor is not None and (region := cursor.visible_region) is not None:
            origin = visible[self][0].y + crop.y
            style = self.get_component_rich_style("cursor--selected")
            selected_strip = Strip([Segment("▌", style)], cell_length=1)
            if CURSOR_BLINK in self.effects and self.animation_visible:
                selected_strip = self.app.colours.paint_mix(self.effect_frame(CURSOR_BLINK), selected_strip)
            for row in range(max(0, region.y - origin), min(crop.height, region.bottom - origin)):
                strips[row] = selected_strip
        return strips


class Window(CoreEventReceiver, HistoryWindow):
    HELP = """\
## Conversation

This is a view of your conversation with the agent.

- **cursor keys** Scroll
- **alt+up / alt+down** Navigate content
- **start typing** Focus the prompt
"""
    BINDING_GROUP_TITLE = "View"
    BINDINGS = [Binding("end", "focus_prompt", "Latest / prompt")]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.jump_bar = containers.Center(
            JumpToLatest("↓ Back to bottom · Esc", id="back-to-bottom"),
            id="back-to-bottom-bar",
        )

    def compose(self) -> ComposeResult:
        yield self.jump_bar

    def on_mount(self) -> None:
        super().on_mount()
        self.tail_follow_changed()

    def _arrange_scrollbars(self, region: Region):
        """Place the vertical bar after the viewport's trailing separator."""
        for scrollbar, scrollbar_region in super()._arrange_scrollbars(region):
            if scrollbar is self.vertical_scrollbar:
                scrollbar_region = scrollbar_region.translate((self.styles.padding.right, 0))
            yield scrollbar, scrollbar_region

    def tail_follow_changed(self) -> None:
        """Show the jump bar while the reader is off the tail; bindings follow only its changes.

        Every scroll offset reaches here, so an unchanged state is no change:
        the footer would otherwise re-project the screen's bindings per frame.
        """
        jump = self.can_jump_to_latest
        if self.jump_bar.display == jump:
            return
        self.jump_bar.display = jump
        if self.is_attached:
            self.query_ancestor(Conversation).refresh_bindings()

    @on(JumpToLatest.Requested)
    def on_back_to_bottom(self, event: JumpToLatest.Requested) -> None:
        event.stop()
        self.query_ancestor(Conversation).jump_to_latest()

    def action_focus_prompt(self) -> None:
        self.query_ancestor(Conversation).focus_prompt()


class AgentWindow(Window):
    """The window of an agent conversation: a drawn frame lets its transcript publish again."""

    def prepare_viewport(self) -> None:
        super().prepare_viewport()
        self.query_ancestor(Conversation).transcript.retry()



class ConversationSessionBinding(WorkspaceHosted, ThreadStatusOwner, containers.Vertical):
    """Source-bound state and reusable rich-surface lifecycle shared by conversations."""

    thread_presentation = None
    """The agent thread's latest settled presentation."""

    _thread_read = None
    """The capture the next observed presentation settles against (ThreadRead)."""

    _unpublished_presentation = None
    """An observed presentation whose transcript refresh waits for this view to be shown."""

    @property
    def operational_sources(self):
        from toad.screens.session_view import SessionView

        return self.query_ancestor(SessionView).presentation.sources

    def transcript_scope(self) -> tuple[str, str] | None:
        """The native session identity whose canonical transcript this view shows."""
        from toad.screens.session_view import SessionView

        origin = self.query_ancestor(SessionView).origin
        return origin.transcript_scope() if origin is not None else None

    def status_thread(self) -> tuple[str, str] | None:
        return self.transcript.thread_scope

    def arm_thread_read(self) -> None:
        """Capture turn token and client authority for the next observed presentation."""
        self._thread_read = self.agent.thread_read() if self.agent is not None else None

    def thread_observed(self, event: core_events.ThreadRowsChanged) -> None:
        """Consume this thread's one observation, including handling and presentation."""
        self.transcript.request_handling()
        presentation = self.app.coordination_access.thread_status.open(self.status_thread()[1]).presentation
        read = self._thread_read
        self.arm_thread_read()
        if read is not None:
            try:
                presentation = read.settle(presentation)
            except ValueError as error:
                self.log.warning("Observed thread presentation not settled", error)
                return
        self.thread_presented(presentation)
        if (prompt := self.query_one_optional(Prompt)) is not None:
            prompt.sync_session()

    def foreign_thread_read(self, presentation) -> None:
        self.thread_presented(presentation)

    def thread_presented(self, presentation) -> None:
        """A settled presentation refreshes the transcript source of the shown view."""
        from toad.screens.session_view import SessionView

        self.thread_presentation = presentation
        if presentation is None or not self.transcript.readable:
            return
        if self.query_ancestor(SessionView).is_current:
            from toad.transcript_publication import ObservedSourcePublication
            self._unpublished_presentation = None
            self.transcript.source_requests.request(ObservedSourcePublication, presentation)
        else:
            self._unpublished_presentation = presentation

    @handles(core_events.SessionSelected)
    async def _thread_view_selected(self, event: CoreEventMessage) -> None:
        from toad.screens.session_view import SessionView

        if not self.query_ancestor(SessionView).is_current:
            return
        self.refresh_thread_status()
        self.goal_observation.invalidate()
        presentation = self._unpublished_presentation
        if presentation is not None:
            from toad.transcript_publication import ObservedSourcePublication
            self._unpublished_presentation = None
            self.transcript.source_requests.request(ObservedSourcePublication, presentation)

    @handles(core_events.ObservedServiceChanged)
    async def _thread_route_observed(self, event: CoreEventMessage) -> None:
        self.refresh_thread_status()

    def bind_agent(self, agent: AgentBase) -> None:
        from toad.agent_surface import AttachedSurfaceBinding

        agent.attach_surface(AttachedSurfaceBinding(self, agent.events))
        self.publish_core(core_events.SessionAgentAttached())

    @abstractmethod
    def _turn_changed(self, owner: TurnOwner) -> None:
        """Publish the concrete conversation's changed turn projection."""
        raise NotImplementedError

    busy_count = var(0)


    visible_categories: var[frozenset[type[MessageCategory]]] = var(lambda: all_categories(), init=False)


    project_path = var("")


    working_directory: var[str] = var("")




    _shell: var[Shell | None] = var(None)




    agent: var[AgentBase | None] = var(None, bindings=True)
    agent_info: var[Content] = var(Content())
    model_history_scope = var("")
    @property
    def queue_supported(self) -> bool:
        return self.agent is not None and self.agent.presentation.queue_supported

    @property
    def model_selection_available(self) -> bool:
        return self.agent is not None and self.agent.configuration.model.available

    @property
    def mode_selection_available(self) -> bool:
        return self.agent is not None and bool(self.agent.available_modes)

    input_delivery: var[InputDelivery] = var(InputDelivery())




    native_history_status: var[type[CursorStatus]] = var(lambda: HiddenCursorStatus)


    goal_display: var[GoalDisplay] = var(NoGoal())


    goal_execution: var[ThreadGoalExecution] = var(IdleGoalExecution())


    status: var[str | Content | RichText] = var("")


    title = var("")


    def __init__(
        self,
        project_path: Path,
        agent: AgentDefinition | None = None,
        agent_session_id: str | None = None,
        session_pk: int | None = None,
        session_title: str | None = None,
        initial_prompt: str | None = None,
        transcript: TranscriptPresentation | None = None,
    ) -> None:
        super().__init__()
        self.turns = ConversationTurn(self._turn_changed, lambda: self.agent.presentation.turns if self.agent else None)
        self.throbber = BelowThrobber(self.working, id="throbber")
        self.throbber_above = AboveThrobber(self.working)
        self._initialize_session(project_path, agent, agent_session_id, session_pk,
                                 session_title, initial_prompt, transcript)


    def _initialize_session(self, project_path, agent=None, agent_session_id=None,
                            session_pk=None, session_title=None, initial_prompt=None,
                            transcript: TranscriptPresentation | None = None) -> None:
        project_path = project_path.resolve().absolute()

        self.set_reactive(ConversationSessionBinding.project_path, project_path)
        self.set_reactive(ConversationSessionBinding.working_directory, str(project_path))
        self.output = LiveOutput(self)
        self._loading: Loading | None = None
        self._mcp_live_note: Note | None = None
        self._private_cursor_sequence = 0
        self.submissions = ConversationSubmissions(self)
        from toad.widgets.agent_activity import AgentActivityBoundary

        self._agent_activity_boundary = AgentActivityBoundary()
        self._last_escape_time = 0.0
        self._agent_data = agent
        self.set_reactive(
            ConversationSessionBinding.model_history_scope, agent.identity if agent else ""
        )
        self._agent_session_id = agent_session_id
        self._session_pk = session_pk
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

        self._initial_prompt = initial_prompt
        self._native_agent_started_here = False

        self.goal_observation = GoalObservation(self)
        self.goal_controls = GoalSession(self)
        self.delivery_observation = InputDeliveryObservation(self)
        self.transcript = transcript if transcript is not None else TranscriptPresentation()
        self.cli_draft = CliDraft()
        self.transcript.bind(self)
        self.tool_expansions: dict[str, bool] = {}
        # Both explicit eviction and Textual unmount consume this same lifetime.
        # The stack removes callbacks before calling them and continues on error.
        self._source_resources = AsyncResourceRelease()
        self._source_resources.push_async_callback(
            SessionObservation.close_all, self.goal_observation, self.delivery_observation,
        )
        self._source_resources.callback(self.output.retire)
        self._source_resources.push_async_callback(self.transcript.detach, self)
        self._source_resources.callback(self.goal_controls.close)

    async def on_unmount(self) -> None:
        async with AsyncResourceRelease() as release:
            release.callback(self._publish_session_end)
            if self.agent is not None:
                release.push_async_callback(self.agent.retire_surface, self)
            release.push_async_callback(self._release_source_resources)

    def _publish_session_end(self) -> None:
        if self._agent_data is not None and self.session_start_time is not None:
            session_time = monotonic() - self.session_start_time
            self.app.application.usage.publish(
                "agent-session-end",
                agent=self._agent_data.identity,
                duration=session_time,
                agent_session_fail=self._agent_fail,
                shell_count=self._shell_count,
                turn_count=self._turn_count,
            )

    async def _release_source_resources(self) -> None:
        """Release the view's acquired sources once, completing every step."""
        await self._source_resources.aclose()

    def take_initial_prompt(self) -> str | None:
        """Transfer pending input to its consumer before releasing this view."""
        prompt, self._initial_prompt = self._initial_prompt, None
        return prompt

    async def release_native_session(self) -> None:
        """Release this view's sources and agent before its tree is removed.

        The view is removed right after (its only caller removes the tree), so
        dropping the agent projects nothing: setting it through its watchers
        restyled the prompt and re-derived the title of a closing tab.
        """
        async with AsyncResourceRelease() as release:
            release.callback(self.take_initial_prompt)
            release.callback(self.set_reactive, Conversation.agent, None)
            await self._release_source_resources()

    async def prepare_retained_session(self) -> None:
        await self.transcript.restore()

    def resume_retained_history(self) -> None:
        """The selected view restores its existing non-native pager resources."""
        for history in self.contents.line_histories():
            history.state.resume_if_parked(history)

    def refresh_native_projection(self) -> None:
        """Publish bound owner facts and invalidate the delivery read resource."""
        agent = self.agent
        if agent is None:
            return
        self.status = agent.context_measurement.status()
        self.turns.bound()
        self.submissions.publish_pending()
        self.delivery_observation.invalidate()



    def start_native_session(self) -> None:
        if self.agent is None and self._agent_data is not None:
            self.screen.frame_presentation.defer(self, self._start_agent)
        elif self.agent is None:
            self.agent_info = Content(self.operational_sources.agent_info(self))
            self._session_ready()
        elif self.agent.ready:
            self._session_ready()

    def _start_agent(self) -> None:
        self.operational_sources.start_agent(self)

    @work
    async def _session_ready(self) -> None:
        """The agent (or the shell) can take input: drop loading, then post start content."""
        presentation = self.transcript
        if presentation.view is not self:
            return
        await self.query(ThreadLoading).remove()
        if self.transcript is not presentation or presentation.view is not self:
            return
        if self._native_agent_started_here and (agent_data := self._agent_data) is not None:
            welcome = agent_data.welcome
            if welcome is not None:
                from toad.widgets.markdown_note import MarkdownNote

                await self.post(MarkdownNote(welcome))
                if self.transcript is not presentation or presentation.view is not self:
                    return
        self._native_agent_started_here = False
        if self.agent is not None and self.agent.configuration.model.requires_selection:
            self.prompt.model_switcher.focus()
            return
        if self._initial_prompt is not None:
            prompt = self._initial_prompt
            if prompt.startswith("!"):
                self.publish_core(
                    input_events.UserInputSubmitted(prompt[1:], shell=True)
                )
            else:
                self.publish_core(
                    input_events.UserInputSubmitted(prompt, shell=False)
                )
            self.take_initial_prompt()

    @handles(core_events.ConfigurationChanged)
    async def on_acp_configuration_changed(self, message: CoreEventMessage):
        self._update_model_info()
        if (prompt := self.query_one_optional(Prompt)) is not None:
            prompt.sync_configuration()
            prompt.sync_session()
        if self._initial_prompt is not None and self.agent is not None and self.agent.ready:
            self._session_ready()
        self.refresh_bindings()

    def _update_model_info(self) -> None:
        agent = self.agent
        model = agent.configuration.model.selected if agent is not None else None
        if model is not None:
            level = agent.configuration.thinking.current
            suffix = f" · {level}" if level else ""
            self.agent_info = Content(model.name + suffix)
        else:
            self.agent_info = (
                Content(self.agent.get_info()) if self.agent is not None else Content()
            )

    @handles(AgentReady)
    async def on_agent_ready(self, message: CoreEventMessage) -> None:
        if not message.event.reconnected:
            self.session_start_time = monotonic()
            if self.agent is not None:
                content = Content.assemble(self.agent.get_info(), " connected")
                self.flash(content, style="success")
                if self._agent_data is not None:
                    self.app.application.usage.publish(
                        "agent-session-begin",
                        agent=self._agent_data.identity,
                    )

        self._session_ready()
        self.prompt.sync_session()
        self.arm_thread_read()
        self.refresh_thread_status()
        self.call_later(self.goal_observation.invalidate)
        self.call_later(self.delivery_observation.invalidate)
        self.transcript.request()

    def watch_agent(self, agent: AgentBase | None) -> None:
        # A presentation remount is not a fresh attachment. Start at the
        # Agent's current projection/floor so previously queued updates cannot
        # revive proof after its reducer entered quarantine or evidence loss.
        if agent is not None:
            self.bind_agent(agent)
        attachments = (agent.presentation.attachments if agent is not None
                       else AgentAttachmentView(HiddenCursorStatus, 0))
        self.native_history_status = attachments.cursor
        self._private_cursor_sequence = attachments.cursor_sequence
        self.submissions.reset()
        # The observed presentation is Core's answer for this thread, not the
        # agent's; it stays until the next observation replaces it.
        self.arm_thread_read()
        if self.is_attached:
            self.refresh_thread_status()
        self.turns.bound()
        self.busy_count = 0
        if agent is None:
            self.agent_info = Content.styled("shell")
        else:
            self._update_model_info()
            self.status = agent.context_measurement.status()
            if agent.ready:
                self._session_ready()
                self.call_later(self.goal_observation.invalidate)
                self.call_later(self.delivery_observation.invalidate)

        if self.is_mounted:
            self.update_slash_commands()


from toad.widget_actions import DeclaredWidgetActions
from toad.conversation_actions import ConversationAction


from toad.delivery_failure_view import DeliveryFailureView


class Conversation(DeliveryFailureView, CoreEventReceiver, DeclaredWidgetActions, ConversationSessionBinding):
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


    contents = getters.query_one("#contents", Contents)
    window = getters.query_one(Window)
    cursor = getters.query_one(CursorContainer)
    prompt = getters.query_one(Prompt)
    app = getters.app(ToadApp)

    def watch_visible_categories(
        self, previous: frozenset[type[MessageCategory]], selected: frozenset[type[MessageCategory]],
    ) -> None:
        from toad.widgets.message_filter import apply_block_filter

        # The reader stays on the message they are reading; when the new
        # selection hides it, on the next message still shown.
        window = self.window
        window.keep_reader()
        self.navigation.clear()
        for block in self.contents.children:
            apply_block_filter(block, selected)
        screen = self.screen
        screen.selections = {
            widget: selection
            for widget, selection in screen.selections.items()
            if all(node.display for node in widget.walk_ancestors(with_self=True))
        }
        for history in tuple(window.histories):
            history.projection_changed()

    def remember_tool_expansion(self, tool_id: str, expanded: bool) -> None:
        """Retain bounded manual disclosure state across canonical transcript remounts."""
        self.tool_expansions.pop(tool_id, None)
        self.tool_expansions[tool_id] = expanded
        if len(self.tool_expansions) > 512:
            del self.tool_expansions[next(iter(self.tool_expansions))]

    @property
    def agent_title(self) -> str | None:
        if self._agent_data is not None:
            return self._agent_data.name
        return None

    def insert_path_into_prompt(self, path: Path) -> None:
        try:
            insert_path_text = str(path.relative_to(self.project_path))
        except ValueError:
            # Paths outside the project have no prompt reference.
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
        self.publish_core(core_events.SessionPathChanged(str(path)))

    async def sync_project_path(self, path: Path) -> None:
        """Apply the owner's project to every cwd-bound part of this view."""
        self.project_path = path
        self.working_directory = str(path)
        self.project_data_path = paths.get_project_data(path)
        self.input_histories.bind_project(self.project_data_path)
        if self._shell is not None and not self._shell.is_finished:
            with suppress(TimeoutError):
                async with asyncio.timeout(2):
                    await self._shell.change_directory(str(path))
        if self.agent is not None:
            self.agent.project_root_path = path
            if (session_pk := self.agent.session.pk) is not None:
                from toad.db import DB

                await DB().session_update_project(session_pk, path)

    def working(self) -> bool:
        return self.busy_count > 0 or self.turns.owner.busy or self._observed_working

    def _sync_working(self) -> None:
        for throbber in (self.throbber, self.throbber_above):
            throbber.sync()

    def _turn_changed(self, owner: TurnOwner) -> None:
        self._sync_working()
        if (prompt := self.query_one_optional(Prompt)) is not None:
            prompt.sync_turn()
        if (details := self.query_one_optional(SessionDetails)) is not None:
            details.sync_turn()
        self.refresh_bindings()

    @on(ObservedThreadActivity.Changed)
    def _observed_activity_changed(self, event: ObservedThreadActivity.Changed) -> None:
        event.stop()
        self._sync_working()

    @on(events.Key)
    async def on_key(self, event: events.Key):
        if self.prompt.prompt_text_area.editing_mode.modal:
            return
        if (
            event.character is not None
            and event.is_printable
            and (event.character.isalnum() or event.character in "$/!")
            and self.window.has_focus
        ):
            self.prompt.focus()
            self.prompt.prompt_text_area.post_message(event)

    def compose(self) -> ComposeResult:
        with AgentWindow():
            with ContentsGrid():
                yield CursorContainer(id="cursor-container")
                with ConversationContents(id="contents"):
                    yield from ThreadLoading.initial_contents(self._agent_data)
                    yield self.cli_draft
        yield Flash()
        with containers.Vertical(id="prompt-stack"):
            from functools import partial
            self.thread_activity = SessionDetails(
                status_source=partial(self.operational_sources.status_row, self),
                transcript=self.transcript,
                history=NativeHistory().data_bind(
                    status=Conversation.native_history_status
                ),
                delivery=InputDeliveryBar().data_bind(
                    delivery=Conversation.input_delivery,
                ),
            )
            self.refresh_thread_status()
            yield self.throbber_above
            yield self.thread_activity
            prompt = self.operational_sources.prompt(self).data_bind(
                project_path=Conversation.project_path,
                working_directory=Conversation.working_directory,
                agent_info=Conversation.agent_info,
                agent=Conversation.agent,
                model_history_scope=Conversation.model_history_scope,
                status=Conversation.status,
            )
            yield self.throbber
            yield GoalBar(self, throbber=self.throbber, prompt=prompt)
            yield prompt

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
            self.navigation.clear()
            self.flash("Command interrupted", style="success")

    def check_directory(self) -> None:
        """A finished turn or command may have changed the project's files."""
        self.prompt.project_directory_updated()
        self.publish_core(input_events.ProjectDirectoryUpdated())

    @on(Terminal.Finalized)
    def on_terminal_finalized(self, event: Terminal.Finalized) -> None:
        """Terminal was finalized, so we can remove it from the list."""
        try:
            self._focusable_terminals.remove(event.terminal)
        except ValueError:
            pass

        self.check_directory()

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


    def draws_user_message(self, sent) -> bool:
        from agent_comms.message_reference import MessageReference

        reference = MessageReference(sent.seq, sent.message_id)
        return any(reference in fragment.notification_references
                   for history in self.transcript.histories
                   for fragment in history.visible_fragments())

    async def _apply_session_name(self, name: str) -> None:
        if self.agent is not None:
            await self.agent.set_session_name(name)
        self.publish_core(core_events.SessionTitleChanged(name))
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

    @handles(core_events.SessionInfoUpdate)
    async def on_session_info_update(
        self, message: CoreEventMessage
    ) -> None:
        if (
            self.agent.coordination.wire_root
            if self.agent and self.agent.coordination
            else None
        ) is not None:
            from toad.core.events import SessionThreadTitle

            self._auto_title_eligible = False
            title = message.event.title or ""
            self.publish_core(SessionThreadTitle(title))
        else:
            from toad.core.events import SessionThreadTitle

            self._auto_title_eligible = False
            title = message.event.title or ""
            self.publish_core(SessionThreadTitle(title))

    @handles(AgentFail)
    async def on_agent_fail(self, message: CoreEventMessage) -> None:
        await self.query(ThreadLoading).remove()
        self.turns.finish_client()
        self._agent_fail = True
        self.prompt.sync_session()
        if (details := self.query_one_optional(SessionDetails)) is not None:
            details.sync_turn()
        self.notify(message.event.message, title="Agent failure", severity="error", timeout=5)

        if self._agent_data is not None:
            self.app.application.usage.publish(
                "agent-session-error",
                agent=self._agent_data.identity,
                message=message.event.message,
                details=message.event.details,
            )

        await SessionDisposition.of(self.agent).present_failure(message.event, self)

    def on_work_started(self) -> None:
        self.busy_count += 1

    def on_work_finished(self) -> None:
        self.busy_count -= 1

    @work
    @handles(input_events.ChangeMode)
    async def on_change_mode(self, event: CoreEventMessage) -> None:
        await self.set_mode(event.event.mode_id)

    @handles(input_events.ProviderLogin)
    def on_provider_login(self, event: CoreEventMessage):
        event.stop()
        self.action_provider_login()

    @work(group="provider-login", exclusive=True)
    async def action_provider_login(self) -> None:
        import shlex
        from textual.geometry import Offset
        from toad.agent_schema import Command
        from toad.catalog_actions import CatalogCommandAction
        from toad.screens.action_modal import ActionModal

        agent = self.agent
        methods = agent.presentation.auth_methods if agent is not None else []
        if not methods:
            self.flash("This agent has not advertised any login methods", style="error")
            return
        method_id = await ContextMenu.choose(
            self.screen,
            Offset(self.prompt.region.x, max(0, self.prompt.region.y - len(methods) - 4)),
            "Connect a provider", [(method.id, method.name) for method in methods],
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
                        CatalogCommandAction.bind("login", Command(method.name, command)),
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
                await agent.session.reconnect_after_login()
            else:
                await agent.session.authenticate(method_id)
            self.flash(
                "Provider login finished; model catalogue refreshed", style="success"
            )
        except (ValueError, OSError, TimeoutError, RequestError) as error:
            self.notify(str(error), title="Provider login", severity="error")
        finally:
            if (prompt := self.query_one_optional(Prompt)) is not None:
                prompt.disabled = False
                prompt.focus()

    @work
    @handles(input_events.ChangeModel)
    async def on_change_model(self, event: CoreEventMessage) -> None:
        if (agent := self.agent) is None:
            return
        # Selecting the current model opens its thinking choices. Reapplying it
        # would ask native SetModel to restore that model's default effort.
        error = None
        if event.event.model_id != agent.configuration.model.current:
            error = await agent.set_model(event.event.model_id)
        if agent is not self.agent:
            return
        if error is not None:
            self.notify(error, title="Set Model", severity="error")
        elif (model := agent.configuration.model.selected) is not None:
            from textual.geometry import Offset

            from toad.db import DB

            # Recent-model persistence is optional metadata, not a prerequisite
            # for opening the model's already advertised thinking choices.
            self.run_worker(DB().record_model_usage(self.model_history_scope, model.value,
                                                   last_used=time_ns()))
            levels = [choice.value for choice in agent.configuration.thinking.choices]
            if len(levels) > 1:
                level = await ContextMenu.choose(
                    self.screen,
                    Offset(self.prompt.region.x, max(0, self.prompt.region.y - len(levels) - 4)),
                    f"Thinking level for {model.name}", [(value, value.title()) for value in levels],
                )
                if (
                    level
                    and (error := await agent.set_thinking_level(level))
                    is not None
                ):
                    self.notify(error, title="Set thinking level", severity="error")
                    return
            self.flash(
                Content.from_markup(
                    "Model [b]$model[/] · thinking [b]$level",
                    model=model.name,
                    level=agent.configuration.thinking.current or "unavailable",
                ),
                style="success",
            )

    @handles(input_events.UserInputSubmitted)
    async def on_user_input_submitted(self, event: CoreEventMessage) -> None:
        event.stop()
        await self.submit_input(event.event)

    async def submit_input(self, event: input_events.UserInputSubmitted) -> None:
        """Wire views override the same submission boundary."""
        await self.submissions.submit(event)

    async def agent_turn_over(self, stop_reason: type[StopReason] | None) -> None:
        """Called when the agent's turn is over.

        Args:
            stop_reason: The stop reason returned from the Agent, or `None`.
        """
        self.turns.finish_client()
        self._agent_activity_boundary.reset()
        model = self.agent.configuration.model.selected if self.agent is not None else None
        if stop_reason is not None and stop_reason.completed and model is not None:
            from toad.db import DB

            # Complete visible turn settlement independently of recent-model
            # database contention. The native worker owns this optional write.
            self.run_worker(DB().record_model_usage(self.model_history_scope, model.value,
                                                   last_used=time_ns()))
        await self.output.settle()
        pending_loading, self._loading = self._loading, None
        if pending_loading is not None and pending_loading.is_attached:
            await pending_loading.remove()
        self.output.boundary()

        self.check_directory()

        self._turn_count += 1


        if stop_reason is not None and stop_reason.note:
            from toad.widgets.markdown_note import MarkdownNote

            await self.post(MarkdownNote(
                stop_reason.note.replace('$AGENT', (self.agent_title or 'agent').title()),
                classes='-stop-reason'))

        if self.app.settings.notifications.turn_over:
            self.app.terminal_attention.notify(
                f"{self.agent_title} has finished working",
                title="Waiting for input",
                sound="turn-over",
            )

    @on(Menu.OptionSelected)
    async def on_menu_option_selected(self, event: Menu.OptionSelected) -> None:
        from toad.screens.session_view import SessionView

        event.stop()
        cursor = self.navigation.cursor
        if (self.query_ancestor(SessionView).is_current and event.action is not None
                and cursor is not None and cursor.accepts(event.owner)):
            await self.run_action(event.action, {"block": event.owner})
        if (cursor_block := self.cursor_block_child) is not None:
            self.call_after_refresh(self.cursor.refresh)

    @handles(CurrentWorkingDirectoryChanged)
    def on_current_working_directory_changed(
        self, event: CoreEventMessage
    ) -> None:
        if self._shell is None or self._shell.pending_directory is None:
            self.working_directory = str(Path(event.event.path).resolve().absolute())

    async def watch_busy_count(self, _busy: int) -> None:
        self._sync_working()

    @on(TerminalTool.Projection)
    async def on_terminal_projection(self, message: TerminalTool.Projection):
        message.stop()
        await message.binding.present_terminal(message, self)

    @handles(core_events.UpdateStatusLine)
    async def on_update_status_line(self, message: CoreEventMessage):
        # The shared widget can receive a queued status message after its
        # source changes. The selected Agent owns the measured value.
        if self.agent is not None:
            self.status = self.agent.context_measurement.status()

    @handles(core_events.RejectedSessionUpdate)
    async def on_rejected_session_update(
        self, message: CoreEventMessage
    ) -> None:
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
        self, message: CoreEventMessage
    ) -> None:
        message.stop()
        if (
            message.publisher is not self.agent
            or self.agent is None
            or message.event.session_id != self.agent.session_id
            or message.event.sequence <= self._private_cursor_sequence
        ):
            return
        self._private_cursor_sequence = message.event.sequence
        self.native_history_status = message.event.update.status

    @handles(core_events.McpClientStopped)
    async def on_mcp_client_stopped(
        self, message: CoreEventMessage
    ) -> None:
        await self._clear_mcp_live()

    async def on_mcp_client_status(self, message: CoreEventMessage) -> None:
        """Show the MCP server summary only within the active turn it describes."""
        # The message carries the validated turn identity; a delayed or queued
        # message from an older agent cannot attach to a successor turn here.
        agent_session = self.agent.session_id if self.agent else None
        if (
            message.publisher is not self.agent
            or (self.agent.current_turn.managed_id if self.agent else None)
            != message.event.update.turn_id
            or self.turns.managed_id is None
            or message.event.update.turn_id != self.turns.managed_id
            or (agent_session is not None and message.event.session_id != agent_session)
        ):
            # Late or forged: the projection dies with its turn and is never
            # shown outside the active-turn lifetime.
            return
        if self._mcp_live_note is not None:
            return  # The package emits at most one server summary per turn.
        rows = message.event.update.acknowledgement.servers
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

    @handles(core_events.Update)
    async def on_acp_agent_message(self, message: CoreEventMessage):
        message.stop()
        if message.publisher is not self.agent:
            return
        if self.turns.owner.busy:
            self.turns.describe("Writing response…")
        await self.output.append(message.event.stream, message.event.text)

    async def on_turn_changed(self, message: CoreEventMessage) -> None:
        if not self.turns.changed(message):
            return
        self.app.events.publish(core_events.OpenTabsChanged())
        if self.turns.owner.busy:
            self.transcript.invalidate_publications()
            return
        await self._clear_mcp_live()
        self._agent_activity_boundary.reset()
        await self.output.settle()
        self.transcript.retry()

    async def on_queue_view_update(self, message: CoreEventMessage) -> None:
        if (
            self.agent is None
            or message.publisher is not self.agent
            or message.event.session_id != self.agent.session_id
        ):
            return
        async with self.window.preserve_history(root=self.contents):
            for started in message.event.update.starts:
                if (
                    message.publisher is not self.agent
                    or message.event.session_id != self.agent.session_id
                ):
                    return
                await self.present_started_input(started)
            self.submissions.publish_pending()

    async def on_input_started(self, message: CoreEventMessage):
        if (
            self.agent is None
            or message.publisher is not self.agent
            or message.event.session_id != self.agent.session_id
        ):
            return
        if message.event.update.text is not None:
            async with self.window.preserve_history(root=self.contents):
                await self.present_started_input(message.event.update)
                self.submissions.publish_pending()

    async def present_started_input(self, started) -> None:
        from toad.widgets.committed_presentation import StartedInputClaim

        self.output.boundary()
        if not self.transcript.covers_input(started.native_id):
            await self.post(UserInput(started.text, claim=StartedInputClaim(started)))
        self.submissions.native_input_presented(started)

    def on_input_failed(self, message: CoreEventMessage) -> None:
        """Only a locally failed request may recover its own draft text."""
        if not self.submissions.accepts_failure(message):
            return
        if not message.event.recover_draft:
            # Server notices (including unstarted queued/restored inputs) are
            # read-only evidence, not permission to change the local composer.
            self.flash(
                f"{message.event.update.failure.title}: {message.event.update.failure.description}\n{message.event.update.failure.input_disposition}\n{message.event.update.failure.action}",
                style="error",
            )
            return
        self.submissions.restore_draft(message.event.update.text)

        self.flash(
            f"{message.event.update.failure.title}; draft restored: {message.event.update.failure.description}\n{message.event.update.failure.input_disposition}\n{message.event.update.failure.action}",
            style="error",
        )

    @handles(TranscriptCoverage)
    async def on_transcript_coverage(self, message: CoreEventMessage) -> None:
        message.stop()
        await self.transcript.covered(message.event, message.publisher)

    @handles(MessageHandlingRequested)
    def request_message_handling(self, message: CoreEventMessage) -> None:
        message.stop()
        self.transcript.request_handling()

    @handles(TranscriptSourceWorkFinished)
    def on_transcript_source_work_finished(self, message: CoreEventMessage) -> None:
        message.stop()
        self.transcript.source_work_finished(message.publisher)

    def on_worker_state_changed(self, message) -> None:
        if message.worker is self.transcript.worker and message.worker.is_finished:
            self.transcript.retry()

    @handles(core_events.Thinking)
    async def on_acp_agent_thinking(self, message: CoreEventMessage):
        self.turns.describe("Thinking…")
        activity = " ".join(message.event.text.splitlines()).strip() or "Thinking"
        await self.output.append(ThoughtStream(), message.event.text)

    @handles(core_events.RequestPermission)
    async def on_acp_request_permission(self, message: CoreEventMessage):
        for request in self.agent.permissions.pending:
            self.request_permissions(request)
        self.output.boundary()

    @handles(core_events.Plan)
    async def on_acp_plan(self, message: CoreEventMessage):
        from toad.widgets.plan import Plan

        if self.contents.children and isinstance(
            (current_plan := self.contents.children[-1]), Plan
        ):
            current_plan.entries = message.event.entries
        else:
            await self.post(Plan(message.event.entries))

    @handles(core_events.ToolCall)
    async def on_acp_tool_call_update(
        self, message: CoreEventMessage
    ):
        await message.publisher.controller.surface.present_tool(message, self)

    @handles(core_events.AvailableCommandsUpdate)
    async def on_acp_available_commands_update(
        self, message: CoreEventMessage
    ):
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
        if (agent := self.agent) is None or mode_id is None:
            return
        error = await agent.set_mode(mode_id)
        if agent is not self.agent:
            return
        if error is not None:
            self.notify(error, title="Set Mode", severity="error")
        elif (mode := agent.current_mode) is not None:
            self.flash(
                Content.from_markup("Mode changed to [b]$mode", mode=mode.name),
                style="success",
            )

    @handles(input_events.HistoryMove)
    async def on_history_move(self, message: CoreEventMessage) -> None:
        message.stop()
        history = self.input_histories.history(message.event.history_kind)
        entry = await history.navigate(message.event.direction, message.event.body)
        history.present(self.prompt, entry)

    @work
    async def request_permissions(self, request) -> None:
        await request.present(self)

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

    async def command_target_context(self):
        from toad.screens.main import MainScreen
        from toad.target_commands import TargetContext
        screen = self.query_ancestor(MainScreen)
        nav = screen.navigation_context
        comms = await self.app.preparation.run_thread(lambda: self.app.coordination_access.service)
        if not self.is_attached or screen.navigation_context != nav:
            raise ValueError('Command view changed during discovery')
        return TargetContext(self.app, comms, nav.actor, nav.actor, nav.project_path, nav.owner_mode)

    @work(group='command-catalog', exclusive=True)
    async def update_slash_commands(self) -> None:
        """Prepare choices only for the prompt that can actually paint them.

        Hidden sources keep their display resource and refresh on selection;
        command execution always reacquires current backend applicability.
        """
        from toad.screens.session_view import SessionView

        if not self.is_attached:
            return
        source = self.query_ancestor(SessionView)
        if not source.is_current:
            return
        try:
            catalog = await self.read_command_catalog()
        except (OSError, ValueError) as error:
            self.prompt.slash_commands = []
            self.flash(str(error), style='error')
        else:
            if self.is_attached and source.is_current:
                self.prompt.slash_commands = catalog.commands

    async def read_command_catalog(self) -> CommandCatalog:
        from toad.screens.session_view import SessionView
        source = self.query_ancestor(SessionView)
        navigation = source.navigation_context
        agent = self.agent
        context = await self.command_target_context()
        catalog = await CommandCatalog.read(self.app,
            agent.presentation.commands if agent is not None else (), context)
        if (not self.is_attached or source.navigation_context != navigation
                or agent is not self.agent):
            raise ValueError('Command view changed during discovery')
        return catalog

    @handles(core_events.LinkContextChanged)
    async def _command_source_changed(self, event: CoreEventMessage) -> None:
        self.prompt.slash_complete.refresh_commands()

    @handles(core_events.SessionSelected, core_events.OpenTabsChanged)
    async def _selected_commands_changed(self, event: CoreEventMessage) -> None:
        self.update_slash_commands()

    async def on_mount(self) -> None:
        await self.initialize_view()

    def apply_layout_preferences(self) -> None:
        """Project the original settings without retaining their semantic values."""
        from toad.setting_choices import Scrollbar

        ui = self.app.settings.ui
        self.styles.max_width = max(10, ui.column_width) if ui.column else None
        for choice in Scrollbar.members_with(Scrollbar):
            self.set_class(choice is ui.scrollbar, f"-scrollbar-{choice.declared_name}")

    async def initialize_view(self) -> None:
        """Initialize the agent view, separate from the framework mount event."""
        self.apply_layout_preferences()
        self.trap_focus()
        self.prompt.focus()
        self.update_slash_commands()
        self.call_after_refresh(self.post_welcome)
        self.observe_core(self.app.saved_settings.events)
        self.observe_core(self.app.events)
        self.observe_core(self.app.coordination_access.events)
        self.transcript.bind_thread_observation()
        self.refresh_thread_status()

        self.input_histories.shell.complete.add_words(
            self.app.settings.shell.allow_commands.split()
        )
        self.start_native_session()
        self.window.anchor()

    @handles(core_events.InputDispositionsChanged)
    async def on_input_dispositions_changed(
        self, event: CoreEventMessage
    ) -> None:
        self.delivery_observation.invalidate()

    @on(DetailAction.Activated, "#session-inspect")
    async def inspect_session(self, event: DetailAction.Activated) -> None:
        event.stop()
        await self.delivery_observation.refresh()
        details = InputDeliveryDetails(
            log_path=self.agent.presentation.log_path if self.agent is not None else None,
            load_history=self.delivery_observation.history,
            dismiss_history=self.delivery_observation.dismiss_history,
        )
        # A modal remains a view of the same backend snapshot, including later starts.
        details.delivery = self.input_delivery
        session_details = self.query_one_optional(SessionDetails)
        if session_details is not None:
            details.overview_text = session_details.overview_text
        self.app.push_screen(details)
        details.watch(
            self, "input_delivery", lambda state: setattr(details, "delivery", state)
        )
        if session_details is not None:
            details.watch(
                session_details,
                "overview_text",
                lambda value: setattr(details, "overview_text", value),
            )

    @handles(core_events.CommsUpdated)
    async def on_comms_updated(self, event: CoreEventMessage) -> None:
        if (event.publisher is not self.agent
                or event.event.session_id != self.agent.session_id):
            event.stop()
            return
        await ConversationCommsConsumer(self, event).dispatch(event.event.update)

    @handles(input_events.GoalControlActivated)
    async def on_goal_control(self, event: CoreEventMessage):
        event.stop()
        await self.goal_controls.activate(event.event.action)

    @work(group="context-compaction")
    async def compact_context(self, instructions: str | None) -> None:
        """Keep processing owner notifications while compaction is in flight."""
        try:
            self.window.anchor()
            self.flash("Compaction requested")
            await self.agent.controller.compact_context(instructions)
            self.flash("Context compacted", style="success")
        except (OSError, ValueError, RequestError) as error:
            self.notify(str(error), title="Compaction request", severity="error")
            self.transcript.require_commit()

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
        # queue. Text/index matching cannot identify a sent input safely.
        if action:
            self._queue_edit_unavailable()

    @work
    async def replace_queued(self, prompts: list[str]) -> None:
        """Never clear-and-resend sent inputs when editing the queue.

        An empty snapshot or control ACK does not prove consumption, and a
        surviving row may be UNKNOWN. Reissuing its text could execute it twice.
        Local unsent composer drafts remain editable without touching this API.
        """
        self._queue_edit_unavailable()

    @handles(PreferenceChanged)
    async def _settings_changed(self, message: CoreEventMessage) -> None:
        if SETTINGS.shell.allow_commands.matches(message.event.field):
            self.input_histories.shell.complete.add_words(
                self.app.settings.shell.allow_commands.split()
            )

    @work
    async def post_welcome(self) -> None:
        """Post any welcome content."""

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
            self.refresh_block_cursor(lambda cursor: cursor.show_clicked(self.window))

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
            if self.transcript.readable:
                # Height pressure is not source evidence. Dropping the source
                # pager or an uncovered wire claim lets a later observation
                # recreate the same record as a new tail arrival.
                if self.contents.virtual_size.height > high_mark:
                    self.transcript.require_commit()
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

        self.navigation.clear()
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
            from toad.agent_surface import AttachedSurfaceBinding

            shell_command = self.app.settings.shell.command
            shell_start = self.app.settings.shell.command_start
            shell_directory = self.working_directory
            self._shell = Shell(
                shell_directory, terminal_size=self.get_terminal_dimensions(),
                shell=shell_command, start=shell_start
            )
            self._shell.start(AttachedSurfaceBinding(self, self._shell.events))
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
        self.refresh_block_cursor(lambda cursor: cursor.show_moved_to(self.window))

    def action_cursor_up(self) -> None:
        self.move_cursor(UpCursor())

    def action_cursor_down(self) -> None:
        self.move_cursor(DownCursor())

    @work
    async def cancel_turn(self, shortcut: str) -> None:
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
            self.flash(f"Press [b]{shortcut}[/] again to cancel agent's turn")
            self._last_escape_time = monotonic()

    def focus_prompt(self, reset_cursor: bool = True, scroll_end: bool = True) -> None:
        """Focus the prompt input.

        Args:
            reset_cursor: Reset the block cursor.
            scroll_end: Scroll t the end of the content.
        """
        if reset_cursor:
            self.navigation.clear()
            self.cursor.refresh()
        if scroll_end:
            self.jump_to_latest()
        self.prompt.focus()

    def jump_to_latest(self) -> None:
        self.window.jump_to_latest()
        self.transcript.request()

    async def action_select_block(self) -> None:
        cursor = self.navigation.cursor
        if cursor is None or (block := cursor.selected) is None:
            return

        menu_options = [
            MenuItem("[u]C[/]opy to clipboard", "copy_to_clipboard", "c"),
            MenuItem("Co[u]p[/u]y to prompt", "copy_to_prompt", "p"),
            MenuItem("Open as S[u]V[/]G", "export_to_svg", "v"),
        ]

        if cursor.allow_maximize:
            menu_options.append(MenuItem("[u]M[/u]aximize", "maximize_block", "m"))

        menu_options.extend(cursor.get_block_menu())
        menu = Menu(block, menu_options, focus_owner=self.window)

        region = cursor.region
        menu.offset = Offset(1, region.y if region is not None else self.window.region.y)
        await self.mount(menu)
        menu.focus()

    def action_copy_to_clipboard(self) -> None:
        cursor = self.navigation.cursor
        if cursor is not None and (text := cursor.get_clipboard_text()):
            self.app.copy_to_clipboard(text)
            self.flash("Copied to clipboard")

    def action_copy_to_prompt(self) -> None:
        cursor = self.navigation.cursor
        if cursor is not None and (text := cursor.get_prompt_text()):
            self.prompt.append(text)
            self.flash("Copied to prompt")
            self.focus_prompt()

    def action_maximize_block(self) -> None:
        cursor = self.navigation.cursor
        if cursor is not None and cursor.allow_maximize:
            cursor.maximize(self.screen)

    def action_export_to_svg(self) -> None:
        cursor = self.navigation.cursor
        if cursor is None or (export := cursor.export_render()) is None:
            return
        import platformdirs
        from textual._files import generate_datetime_filename

        size, render = export
        width, height = size

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

    def refresh_block_cursor(self, show) -> None:
        """Paint the cursor's new block; `show` scrolls for how the cursor got there."""
        self.cursor.refresh()
        if (cursor := self.navigation.cursor) is not None:
            # Resolve this navigation event before a later tab/editor event.
            self.screen.set_focus(self.window)
            self.call_after_refresh(
                self._present_block_cursor, cursor, show
            )
        else:
            self.window.anchor()
            self.prompt.focus()
        self.refresh_bindings()

    def _present_block_cursor(self, cursor, show) -> None:
        from toad.screens.session_view import SessionView

        # A later prompt, tab or source event may already have moved the cursor
        # off this block.
        if (self.is_attached and not self.is_leaving
                and self.query_ancestor(SessionView).is_current
                and self.navigation.cursor is cursor):
            show(cursor)
            self.cursor.refresh()
            self.refresh_bindings()

class ConversationCommsConsumer(MroDispatch):
    def __init__(self, conversation, message):
        self.conversation = conversation
        self.message = message

    @handles(CoordinationChangedUpdate)
    async def coordination_changed(self, update: CoordinationChangedUpdate):
        # Source binding is published independently of registry/activity changes:
        # a newly bound thread joins the observed threads (or reads as foreign).
        self.conversation.arm_thread_read()
        self.conversation.refresh_thread_status()
        self.conversation.prompt.sync_session()
        self.conversation.prompt.sync_queue()

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
        self.conversation.goal_observation.receive(self.message.publisher, update)

    @handles(CompactionChangedUpdate)
    async def compaction_changed(self, update: CompactionChangedUpdate):
        await CompactionRenderer(self.conversation).dispatch(update.event)

    @handles(TranscriptSnapshotUpdate)
    async def transcript_snapshot(self, update: TranscriptSnapshotUpdate):
        await self.conversation.transcript.snapshot(update.page)

    @handles(McpClientAcknowledgementUpdate)
    async def mcp_status(self, update: McpClientAcknowledgementUpdate):
        await self.conversation.on_mcp_client_status(self.message)



class CompactionRenderer(MroDispatch):
    def __init__(self, conversation):
        self.conversation = conversation

    @handles(comms_events.CompactionEnd)
    async def end(self, event):
        # Pi's saved compaction entry owns the notice; re-read the transcript.
        self.conversation.transcript.require_commit()
