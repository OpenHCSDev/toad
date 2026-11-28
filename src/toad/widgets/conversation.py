from __future__ import annotations

import asyncio
import io
import os.path
import shlex
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from functools import cached_property
from itertools import filterfalse
from operator import attrgetter
from pathlib import Path
from time import monotonic, time_ns
from typing import Callable, ClassVar

import platformdirs
from acp import schema as acp_protocol
from acp.exceptions import RequestError
from agent_comms.acp_extension import McpClientAcknowledgementUpdate
from agent_comms.execution.transcript_sources import TranscriptCursor
from agent_comms.planning.goal_presentation import (
    GoalExecutionControls,
    IdleGoalExecution,
)
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.planning.goals import NoGoal
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.registry.thread_presentation import (
    NoThreadPresentation,
    ThreadPresentation,
)
from agent_comms.ui_model.delivery import DeliveryView
from agent_comms.ui_model.goal import GoalDisplay
from agent_comms.ui_model.message_category import (
    AgentActivityBoundary,
    OtherCategory,
    MessageCategory,
    all_categories,
)
from metaclass_registry.mro_dispatch import MroDispatch, handles

from toad.client.view_binding_protocols import BoundViewHost
from toad.client.session_sources import SourcedConversation
from toad.client.thread_binding_dispatch import ThreadBindingDispatch
from toad.core.link_context_changed import LinkContextChanged
from toad.flash_host import FlashHost
from rich.console import Console
from rich.segment import Segment
from rich.style import Style
from formbridge.key_declarations import TextEntryMode
from textual import containers, events, getters, on, work
from textual._files import generate_datetime_filename
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.app import ComposeResult
from textual.content import Content
from textual.css.native import NativeDeclaration, Variable
from textual.css.query import NoMatches
from textual.css.styles import Styles
from textual.document._editing import EditingMode
from textual.dom import DOMNode
from textual.geometry import Offset, Region, Size
from textual.layout import WidgetPlacement
from textual.layouts.grid import GridLayout
from textual.reactive import Required, var
from textual.strip import Strip
from textual.view import AUTO, FILL
from textual.widget import Widget
from textual.widgets import Static
from toad.column_layout import ColumnLayout
from ui_theme.effects import CURSOR_BLINK, Mix
from ui_theme.scheme import BackgroundColour, ForegroundColour, SurfaceHoverColour

from toad import about, messages, paths
from toad.acp.attachment_presentation import CursorPresentation
from toad.acp.comms_updates import ThreadRead
from toad.acp.status import StopReason
from toad.agent import AgentBase
from toad.agent_binding import AgentConnection, NoAgentConnection
from toad.answer import Answer
from toad.block_navigation import (
    AbsentEntry,
    BlockCursor,
    ContentNavigation,
    ConversationEntry,
    CursorDirection,
    SeparatedBlock,
    require_blocks,
)
from toad.client.conversation_session_binding import ConversationThreadReadMixin
from toad.client.conversation_sources import ConversationSources
from toad.client.submission import SubmissionStart
from toad.category_filter import CategoryFilterView
from toad.command_catalog import AddressesItsThread, ReadsCommandCatalog
from toad.command_target_scope import CommandTargetScope
from toad.conversation_actions import ConversationAction, WindowAction
from toad.conversation_comms_handlers import ConversationCommsHandlers
from toad.conversation_submission import AgentInputSubmission, ConversationSubmissions
from toad.conversation_turn import ConversationTurn, TurnOwner
from toad.core import events as core_events, input_events, session_requests
from toad.core.configuration_events import ChangeConfiguration, ChangeModel
from toad.core.events import AgentFail, AgentReady
from toad.core.preference_events import PreferenceChanged
from toad.core.source_events import CurrentWorkingDirectoryChanged
from toad.core_event_carrier import CoreEventMessage, CoreEventReceiver
from toad.delivery_failure_view import DeliveryFailureView
from toad.frame_presentation import Animated
from toad.goal_controls import GoalSource
from toad.goal_interaction import GoalSession
from toad.goal_view import GoalView
from toad.client.input_decision import InputDecision
from toad.input_history import InputHistories
from toad.launch_binding import AgentBinding, AgentConversation, NoAgent
from toad.layout import trim_trailing_margin
from toad.layout_preferences import FollowsLayoutPreferences
from toad.client.line_blocks import LineLink
from toad.live_output import LiveOutput
from toad.menus import MenuConversation
from toad.messages import QueueEvidenceOwner
from toad.native_style import (
    AutoHeight,
    AutoWidth,
    CenteredChildren,
    CenteredText,
    DockedBottom,
    FillWidth,
    PrimaryText,
    RightPadding,
    ScreenOverlay,
    SidePadding,
    StableGutter,
    StartsHidden,
)
from toad.navigation_context import NavigationScope
from toad.preferences import SETTINGS
from toad.private_native_cursor import CursorStatus, HiddenCursorStatus
from toad.client.resource_release import AsyncResourceRelease
from toad.screens.queue import QueueInspection
from toad.session_clock import NotStarted, SessionClock, StartedAt
from toad.session_observation import (
    GoalObservation,
    InputDeliveryObservation,
    SessionObservation,
)
from toad.session_scope import SessionScope
from toad.shell import Shell
from toad.status_thread import StatusThread
from toad.submission_queue import QueueSource
from toad.client.commands import AgentConversationCommands
from toad.screens.team import TeamPage
from toad.transcript_publication import (
    BoundView,
    ObservedSourcePublication,
    SourcePublicationWork,
    TranscriptPresentation,
    ViewBinding,
    WindowPublicationWork,
)
from toad.transcript_scope import TranscriptScope, TranscriptView
from toad.view_actions import LatestJumpBar, ShowsLatestJumpBar
from toad.workspace_frame import WorkspaceHosted
from toad.widgets.cli_draft import DRAFT_PRESENTATION, CliDraft
from toad.widgets.presentation_window import protected_presentations
from toad.client.history_state import LiveTranscript
from toad.screens.session_view import SessionView
from textual.worker import get_current_worker
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.flash import ErrorFlash, Flash, SuccessFlash
from toad.widgets.goal_bar import GoalBar
from toad.widgets.history_anchor import HistoryWindow
from toad.client.history_changes import PinsMessageHeader
from toad.client.fragments import FragmentKey
from toad.client.reader_position import FragmentPosition
from toad.widgets.input_delivery import InputDeliveryBar, InputDeliveryDetails
from toad.widgets.markdown_note import MarkdownNote, StopReasonNote
from toad.widgets.menu import Menu
from toad.widgets.message_divider import AgentActivityDivider, StickyHeader
from toad.client.history_notifications import SourceNotifications
from toad.widgets.message_notifications import VisibleHistoryNotifications
from toad.client.history_reads import NothingToRead, PaintedRead
from toad.widgets.native_history import NativeHistory
from toad.widgets.note import ErrorNote, Note
from toad.status_thread import WorkingStatusOwner
from toad.widgets.observed_thread_activity import ObservedThreadActivity
from toad.widgets.prompt import Prompt
from toad.widgets.session_details import OperationalSessionDetails, SessionDetails
from toad.widgets.shell_terminal import ShellTerminal
from toad.widgets.splash_text import ThreadLoading
from toad.widgets.terminal import Terminal
from toad.widgets.terminal_tool import TerminalTool
from toad.widgets.throbber import AboveThrobber
from toad.widgets.transcript_history import JumpToLatest, LineHistory, TranscriptHistory
from toad.widgets.user_input import UserInput
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.turn_presentation import TurnPresentation

from toad.widgets.transcript_lines import LineTarget


from toad.session_titles import FirstPromptTitle


from agent_comms.nominal.field_codec import AcpSessionId, NoAcpSessionId

from toad.answer import Ask

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


class Loading(PrimaryText, SeparatedBlock, Static):
    """A transient notice inherits native outside-border separation."""


class CategorizedMount:
    """Mount blocks in their declared order with the conversation's category selection."""

    def mount(self, *widgets, before=None, after=None):
        blocks = require_blocks(widgets)
        orders = {block.conversation_order for block in blocks}
        if before is not None or after is not None or len(orders) != 1:
            mounted = super().mount(*blocks, before=before, after=after)
            self.sort_children(key=lambda block: block.conversation_order)
        else:
            # Children stay ordered, so blocks of one order go after the last
            # child not above it: a live append (the common case) lands at the
            # tail without visiting, sorting or relaying out the conversation.
            (order,) = orders
            children = self.children
            index = len(children)
            for index in range(len(children), 0, -1):
                if children[index - 1].conversation_order <= order:
                    break
            else:
                index = 0
            if index == len(children):
                mounted = super().mount(*blocks)
            else:
                mounted = super().mount(*blocks, before=children[index])
        # Registration supplies the history's real parent before its filter
        # prepares a projection; both still happen before first mount/paint.
        selected = self.selected_categories
        for widget in blocks:
            widget.apply_message_filter(selected)
        self.call_after_refresh(self.check_notifications)
        return mounted


class Contents(VisibleHistoryNotifications, LineTarget, containers.VerticalGroup, can_focus=False):
    CACHE_SUBTREE_GEOMETRY = True
    BLANK = True

    def line_histories(self):
        """Visit history containers without entering their rich bodies."""

        pending = list(reversed(self.children))
        while pending:
            child = pending.pop()
            if isinstance(child, LineHistory):
                yield child
                pending.extend(reversed(child.children))

    @property
    def can_draw_on_screen(self):
        return self.is_attached and self.is_on_screen

    def notification_targets(self) -> tuple[SourceNotifications, ...]:
        return tuple(
            history
            for history in self.screen._compositor.visible_widgets
            if isinstance(history, SourceNotifications)
            and history.notification_view is self
        )

    @property
    def line_width(self) -> int:
        """The native width of full-width history rows prepared before mounting."""
        return self.content_size.width

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        return all_categories()

    async def prepare_history(
        self,
        history: LineHistory,
        current: Callable[[], bool],
        *,
        window: HistoryWindow,
    ) -> None:
        """Supply a laid-out native target before its detached history prepares rows."""
        if not self.line_width:
            await self.screen.layout_in_steps()
        rows, _limit = window.latest_limits(history.budget)
        await history.prepare_rows(
            current,
            window=window,
            target=self,
            selected=self.selected_categories,
            rows_needed=rows,
        )

    @height_dependency(INDEPENDENT_HEIGHT)
    def process_layout(
        self, placements: list[WidgetPlacement]
    ) -> list[WidgetPlacement]:
        return trim_trailing_margin(placements)


class ConversationContents(CategorizedMount, Contents):
    """Conversation ordering and categories compose with the native row container."""

    def notification_targets(self):
        return (
            *super().notification_targets(),
            *(
                target
                for child in self.screen._compositor.visible_widgets
                if child.parent is self
                for target in child.notification_targets()
            ),
        )

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        return (
            self.query_ancestor(CategoryFilterView).visible_categories
            if self.is_attached
            else all_categories()
        )


class ContentsGrid(AutoHeight, containers.Grid):
    """The cursor rail's column beside the conversation's rows."""

    BLANK = True

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.grid_size_columns = 2
        self.styles.grid_columns = (1, FILL)
        self.styles.grid_rows = (AUTO,)

    @height_dependency(INDEPENDENT_HEIGHT)
    def pre_layout(self, layout) -> None:
        assert isinstance(layout, GridLayout)
        layout.stretch_height = True


class CursorContainer(Animated[Mix], Static):
    """Paint navigation over content geometry without authoring document extent.

    One column: a faint rail, and the blinking accent bar beside the rows the cursor rests on.
    """

    RAIL: ClassVar[Mix] = Mix(BackgroundColour, ForegroundColour, 0.07)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.styles.width = 1

    @on(events.Mount)
    def on_mount(self) -> None:
        self.watch(
            self.query_ancestor(Window), "has_focus", self.app.colours.clock.refresh
        )
        self.run_effect(CURSOR_BLINK)

    @property
    def animation_visible(self) -> bool:
        return super().animation_visible and self.query_ancestor(Window).has_focus

    def _effect_region(self) -> Region | None:
        cursor = self.query_ancestor(Conversation).navigation.cursor
        visible = cursor.visible_region
        if not isinstance(visible, Region):
            return None
        if visible.height == 0:
            return Region(0, 0, 1, 0)
        return Region(0, visible.y - self.region.y, 1, visible.height)

    def render_lines(self, crop: Region) -> list[Strip]:
        colours = self.app.colours
        strips = [colours.paint_mix(self.RAIL, Strip([Segment("▌")], cell_length=1))] * crop.height
        if crop.y == 0 and strips:
            strips[0] = Strip([Segment(" ")], cell_length=1)
        # Selection belongs to ContentNavigation. The published scene supplies
        # its current position, including nested and lazily replaced bodies.
        # This column's own placement is the fact the compositor's arranged map would only
        # restate, and asking that map for it by key raised KeyError: CursorContainer() in a
        # frame that cropped none of this column (Toad log KeyError_2026-11-07T15_52_49).
        cursor = self.query_ancestor(Conversation).navigation.cursor
        selected = colours.paint_mix(self.effect_frame(CURSOR_BLINK), Strip([Segment("▌")], cell_length=1))
        for row in cursor.visible_region.rows_within(self.region.y + crop.y, crop.height):
            strips[row] = selected
        return strips


class FocusPromptAction(WindowAction):
    """Go to the latest content and focus its prompt."""

    keys = {TextEntryMode: ("end",)}
    show = True

    def apply(self, window: Window) -> None:
        window.query_ancestor(Conversation).focus_prompt()


class JumpBar(
    LatestJumpBar,
    StartsHidden,
    ScreenOverlay,
    DockedBottom,
    FillWidth,
    CenteredChildren,
    containers.Center,
):
    """A transparent row floated over the window's foot; only its button shows."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.layer = "float"
        self.styles.height = 3
        self.styles.visibility = "hidden"

    @property
    def jump_shown(self) -> bool:
        return bool(self.display)

    def show_jump(self, shown: bool) -> None:
        self.display = shown


class BackToBottom(PrimaryText, CenteredText, AutoWidth, AutoHeight, SidePadding, JumpToLatest):
    """Two rows of its own: JumpToLatest is one row, and this one names its key below.

    CenteredText because its rows are different widths: the key row is shorter than the
    name above it and would otherwise start at the left edge.
    """

    native_theme = (NativeDeclaration.of(Styles.background, Variable(SurfaceHoverColour.name)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.visibility = "visible"
        self.styles.text_style = Style(bold=True)


class Window(
    ShowsLatestJumpBar,
    RightPadding,
    StableGutter,
    CoreEventReceiver,
    HistoryWindow,
    PinsMessageHeader,
    actions=(WindowAction,),
):
    HELP = """\
## Conversation

This is a view of your conversation with the agent.

- **cursor keys** Scroll
- **alt+up / alt+down** Navigate content
- **start typing** Focus the prompt
"""
    BINDING_GROUP_TITLE = "View"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.jump_bar = JumpBar(BackToBottom(JumpBar.label))
        self.sticky_header = StickyHeader(self)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.align = ("left", "bottom")

    def compose(self) -> ComposeResult:
        yield self.sticky_header
        yield self.jump_bar

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        self.repin_header()

    def message_top(self, key: FragmentKey) -> float | None:
        location = FragmentPosition(key, 0.0, 1, block=0).page(self)
        return location.destination(self, 0.0) if location.laid_out(self) else None

    def prepare_viewport(self) -> None:
        """Committed geometry can change the top row's message at an unchanged offset
        (a reflow, a filter, replaced pages, a restored tab); pin from that scene too."""
        super().prepare_viewport()
        self.repin_header()

    @on(events.Mount)
    def on_mount(self) -> None:
        super().on_mount()
        self.tail_follow_changed()

    def _arrange_scrollbars(self, region: Region):
        """Place the vertical bar after the viewport's trailing separator."""
        for scrollbar, scrollbar_region in super()._arrange_scrollbars(region):
            if scrollbar is self.vertical_scrollbar:
                scrollbar_region = scrollbar_region.translate(
                    (self.styles.padding.right, 0)
                )
            yield scrollbar, scrollbar_region

    def _after_jump_bar_change(self, shown: bool) -> None:
        if self.is_attached:
            self.query_ancestor(Conversation).refresh_bindings()

    @on(events.Key)
    def hand_typing_to_the_prompt(self, event: events.Key) -> None:
        """Typing in the window is typing in the prompt. A key the window received after the
        burst moved focus belongs to the prompt's typing target, so a burst arrives whole and
        in order."""
        conversation = self.query_ancestor(Conversation)
        if self.has_focus:
            if not conversation.starts_typing(event):
                return
            conversation.start_typing()
        elif self.has_focus_within:
            return
        event.stop()
        event.prevent_default()
        target = conversation.prompt.typing_target
        if target is not None:
            target.post_message(events.Key(event.key, event.character))

    @on(JumpToLatest.Requested)
    def on_back_to_bottom(self, event: JumpToLatest.Requested) -> None:
        event.stop()
        self.query_ancestor(Conversation).jump_to_latest()


class AgentWindow(Window):
    """The window of an agent conversation: a drawn frame lets its transcript publish again."""

    def prepare_viewport(self) -> None:
        super().prepare_viewport()
        self.query_ancestor(Conversation).transcript.retry()


class ConversationSessionBinding(
    ConversationThreadReadMixin,
    MroDispatch,
    ThreadBindingDispatch,
    WorkspaceHosted,
    WorkingStatusOwner,
    DeliveryFailureView,
    AgentConversation,
    CategoryFilterView,
    TurnPresentation,
    containers.Vertical,
):
    """Source-bound state and reusable rich-surface lifecycle shared by conversations."""

    contents = getters.query_one(ConversationContents)
    thread_presentation: ThreadPresentation = NoThreadPresentation()

    @property
    def transcript_history(self) -> TranscriptHistory:
        """The single TranscriptHistory child BoundView drives. Kept here so Textual's
        Conversation answers the shared BoundViewHost contract — Qt's views answer
        the same member with their own history."""
        history, = self.contents.query_children(TranscriptHistory)
        return history
    """The agent thread's latest settled presentation."""

    _unpublished_presentation: ThreadPresentation = NoThreadPresentation()
    """An observed presentation whose transcript refresh waits for this view to be shown."""

    @property
    def is_current_session(self) -> bool:
        """Whether this conversation's owning session is still selected."""
        return self.query_ancestor(SessionScope).is_current

    @cached_property
    def navigation(self) -> ContentNavigation:
        return ContentNavigation(self.contents)

    def accepts_menu_owner(self, owner: Widget) -> bool:
        return self.is_current_session and self.navigation.accepts_menu_owner(owner)

    def open_line_link(self, link: LineLink) -> None:
        self.transcript.binding.history.dispatch_sync(link)

    @property
    def operational_sources(self) -> ConversationSources:
        return self.query_ancestor(SourcesScope).operational_sources

    @property
    def goal_source(self) -> GoalSource:
        """Where this view reads and changes its owner's goal: its sources say (an agent's, or
        Core's for a CLI's mailbox)."""
        return self.operational_sources.goal_source(self)

    def goal_owner(self) -> ThreadIncarnation | None:
        """The thread incarnation whose goal this view shows, once its session names one."""
        return self.query_ancestor(SessionScope).thread_identity.optional_thread_incarnation()

    @property
    def coordination_root(self) -> str | None:
        """The bus root the view's session reads its thread from."""
        return self.query_ancestor(SessionScope).coordination_root

    def transcript_scope(self) -> TranscriptScope:
        """The native session identity whose canonical transcript this view shows."""
        return self.query_ancestor(SessionScope).origin.transcript_scope()

    @abstractmethod
    def thread_presented(self, presentation: ThreadPresentation) -> None: ...

    @handles(NoThreadPresentation)
    def _no_thread_source(self, presentation: NoThreadPresentation) -> object:
        self._unpublished_presentation = presentation
        return self.DISCARD

    def bind_agent(self, agent: AgentConnection) -> None:
        self.agent_binding = agent
        agent.attach_view(self)

    @property
    def bound_agent(self) -> AgentConnection:
        """The reactive `agent_binding`: `NoAgentConnection` until a live agent binds, as
        `AgentBoundConversation.bound_agent` answers."""
        return self.agent_binding

    def apply_bound_agent(self, agent: AgentBase) -> None:
        self._update_model_info()
        self.thread_status = agent.context_measurement.status()
        if agent.ready:
            self.session_ready()
            self.call_later(self.goal_observation.invalidate)
            self.call_later(self.delivery_observation.invalidate)

    def agent_connected(self, agent: AgentBase) -> None:
        self.feedback.flash(Content.assemble(agent.get_info(), " connected"), style="success")
        self.launch.publish_usage(self.app.application.usage.publish, "agent-session-begin")

    async def cancel_bound_turn(self, agent: AgentBase) -> None:
        self.feedback.flash("Cancelling agent turn…")
        self.turns.describe("Cancelling…")
        if self._loading is not None and self._loading.is_attached:
            self._loading.update("Cancelling…")
        if await agent.cancel():
            self.feedback.flash("Turn cancelled", style="success")
        else:
            self.feedback.flash("Agent declined to cancel. Please wait.", style="error")

    @abstractmethod
    def _turn_changed(self, owner: TurnOwner) -> None:
        """Publish the concrete conversation's changed turn projection."""

    project_path = var[Checkout](Required())

    working_directory: var[str] = var("")

    _shell: var[Shell | None] = var(None)

    agent_binding: var[AgentConnection] = var(NoAgentConnection, bindings=True)
    agent_info: var[Content] = var(Content())
    model_history_scope = var("")

    def show_agent_info(self, text: str) -> None:
        """The info bar's agent text, which shared owners answer as plain text."""
        self.agent_info = Content(text)

    @property
    def mode_selection_available(self) -> bool:
        return bool(self.agent_binding.available_modes)

    input_delivery: var[DeliveryView] = var(DeliveryView())

    native_history_status: var[type[CursorStatus]] = var(lambda: HiddenCursorStatus)

    goal_display: var[GoalDisplay] = var(NoGoal())

    goal_execution: var[GoalExecutionControls] = var(IdleGoalExecution())

    title = var("")

    def __init__(
        self,
        project_path: Checkout,
        launch: AgentBinding = NoAgent(),
        agent_session_id: AcpSessionId | NoAcpSessionId = NoAcpSessionId(),
        session_pk: int | None = None,
        session_title: str | None = None,
        initial_prompt: str | None = None,
        transcript: TranscriptPresentation | None = None,
    ) -> None:
        super().__init__()
        self.turns = ConversationTurn(
            self._turn_changed, lambda: self.agent_binding.presentation.turns
        )
        self.throbber_above = AboveThrobber(self.working)
        self._initialize_session(
            project_path,
            launch,
            agent_session_id,
            session_pk,
            session_title,
            initial_prompt,
            transcript,
        )

    def _initialize_session(
        self,
        project_path: Checkout,
        launch: AgentBinding = NoAgent(),
        agent_session_id: AcpSessionId | NoAcpSessionId = NoAcpSessionId(),
        session_pk: int | None = None,
        session_title: str | None = None,
        initial_prompt: str | None = None,
        transcript: TranscriptPresentation | None = None,
    ) -> None:
        self.set_reactive(ConversationSessionBinding.project_path, project_path)
        self.set_reactive(
            ConversationSessionBinding.working_directory, str(project_path)
        )
        self.output = LiveOutput(self)
        self._loading: Loading | None = None
        self._mcp_live_note: Note | None = None
        self._private_cursor_sequence = 0
        self.submissions = ConversationSubmissions(self)
        self._agent_activity_boundary = AgentActivityBoundary()
        self._last_escape_time = 0.0
        self.launch = launch
        self._thread_loading = ThreadLoading.initial_contents(launch)
        self.set_reactive(
            ConversationSessionBinding.model_history_scope,
            launch.selected_agent("", attrgetter("identity")),
        )
        self._agent_session_id = agent_session_id
        self._session_pk = session_pk
        self._auto_title_eligible = (
            not agent_session_id.bound and session_title is None
        )
        self._agent_fail = False
        self._mouse_down_offset: Offset | None = None

        self._focusable_terminals: list[Terminal] = []

        self.project_data_path = paths.get_project_data(project_path)
        self.input_histories = InputHistories(
            self.project_data_path,
            agent_session_id.selected(
                f"session-{session_pk}" if session_pk is not None else "", str
            ),
        )

        self.session_clock: SessionClock = NotStarted()
        self._terminal_count = 0
        self._require_check_prune = False

        self._turn_count = 0
        self._shell_count = 0

        self._initial_prompt = initial_prompt
        self._native_agent_started_here = False

        self.goal_observation = GoalObservation(self)
        self.goal_controls = GoalSession(self)
        self.delivery_observation = InputDeliveryObservation(self)
        self.transcript = (
            transcript if transcript is not None else TranscriptPresentation()
        )
        self.cli_draft = CliDraft()
        self.tool_expansions: dict[str, bool] = {}
        # Both explicit eviction and Textual unmount consume this same lifetime.
        # The stack removes callbacks before calling them and continues on error.
        self._source_resources = AsyncResourceRelease()
        self._source_resources.push_async_callback(
            SessionObservation.close_all,
            self.goal_observation,
            self.delivery_observation,
        )
        self._source_resources.callback(self.output.retire)
        self._source_resources.push_async_callback(self.transcript.detach, self)
        self._source_resources.callback(self.goal_controls.close)

    @on(events.Unmount)
    async def on_unmount(self) -> None:
        async with AsyncResourceRelease() as release:
            release.callback(self._publish_session_end)
            release.push_async_callback(self.agent_binding.retire_surface, self)
            release.push_async_callback(self._release_source_resources)

    def _publish_session_end(self) -> None:
        self.session_clock.report_end(
            self.launch,
            self.app.application.usage.publish,
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
            release.callback(
                self.set_reactive, Conversation.agent_binding, NoAgentConnection()
            )
            await self._release_source_resources()

    def resume_retained_history(self) -> None:
        """The selected view restores its existing non-native pager resources."""
        for history in self.contents.line_histories():
            history.state.resume_if_parked(history)

    @work
    async def session_ready(self) -> None:
        """The agent (or the shell) can take input; page publication owns the splash."""
        presentation = self.transcript
        if not presentation.binding.matches(self):
            return
        if self._native_agent_started_here:
            welcome = self.launch.selected_agent(None, attrgetter("welcome"))
            if welcome is not None:

                await self.post(MarkdownNote(welcome))
                if (
                    self.transcript is not presentation
                    or not presentation.binding.matches(self)
                ):
                    return
        self._native_agent_started_here = False
        if self.agent_binding.configuration.model.requires_selection:
            self.prompt.model_switcher.focus()
            return
        if self._initial_prompt is not None:
            prompt = self._initial_prompt
            if prompt.startswith("!"):
                self.publish_core(
                    input_events.UserInputSubmitted(prompt[1:], shell=True)
                )
            else:
                self.publish_core(input_events.UserInputSubmitted(prompt, shell=False))
            self.take_initial_prompt()

    @handles(core_events.ConfigurationChanged)
    async def on_acp_configuration_changed(self, event: core_events.ConfigurationChanged) -> None:
        self._update_model_info()
        for prompt in self.query(Prompt):
            prompt.sync_configuration()
            prompt.sync_session()
        if self._initial_prompt is not None and self.agent_binding.ready:
            self.session_ready()
        self.refresh_bindings()

    def _update_model_info(self) -> None:
        self.show_agent_info(self.agent_binding.model_info(self.agent_title))

    @handles(AgentReady)
    async def on_agent_ready(self, event: AgentReady) -> None:
        if not event.reconnected:
            self.session_clock = StartedAt(monotonic())
            self.agent_binding.connected(self)

        self.session_ready()
        self.prompt.sync_session()
        self.arm_thread_read()
        self.refresh_thread_status()
        self.call_later(self.goal_observation.invalidate)
        self.call_later(self.delivery_observation.invalidate)
        self.transcript.binding.request(self.transcript)

    def watch_agent_binding(self, binding: AgentConnection) -> None:
        # A presentation remount is not a fresh attachment. Start at the
        # Agent's current projection/floor so previously queued updates cannot
        # revive proof after its reducer entered quarantine or evidence loss.
        attachments = binding.presentation.attachments
        self.native_history_status = attachments.cursor
        self._private_cursor_sequence = attachments.cursor_sequence
        self.submissions.reset()
        # The observed presentation is Core's answer for this thread, not the
        # agent's; it stays until the next observation replaces it.
        self.arm_thread_read()
        if self.is_attached:
            self.refresh_thread_status()
        self.turns.bound()
        binding.update_view(self)

        if self.is_mounted:
            self.update_slash_commands()


from toad.client.agent_schema import Command
from toad.agent_surface import AttachedSurfaceBinding
from toad.agent_turn_events import AgentTurnEvents
from toad.catalog_actions import CatalogCommandAction
from toad.commit_claims import StartedInputClaim
from toad.client.db import DB
from toad.screens.action_modal import ActionModal
from toad.widget_actions import DeclaredWidgetActions, NativeMethodKeys
from toad.widgets.plan import ConversationPlan


class PromptStack(DockedBottom, AutoHeight, containers.Vertical):
    """The controls docked under the window: activity, goal and prompt."""


class SourcesScope(DOMNode):
    """The ancestor that presents a conversation: its sources, and the editing mode its prompt
    starts in."""

    @property
    @abstractmethod
    def operational_sources(self) -> ConversationSources: ...

    @property
    @abstractmethod
    def initial_editing_mode(self) -> EditingMode: ...


class RequestedModeId(ABC):
    """Optional agent mode identifier requested for Conversation.set_mode."""

    async def apply_to_conversation(self, owner: Conversation) -> None:
        pass

    @classmethod
    def from_optional(cls, value: str | None) -> RequestedModeId:
        return AbsentRequestedModeId() if value is None else HeldRequestedModeId(value)


@dataclass(frozen=True)
class AbsentRequestedModeId(RequestedModeId):
    """Absent `RequestedModeId` carrying no value."""


@dataclass(frozen=True)
class HeldRequestedModeId(RequestedModeId):
    """Held `RequestedModeId` carrying its present value."""

    value: str

    async def apply_to_conversation(self, owner: Conversation) -> None:
        agent = owner.agent_binding
        error = await agent.set_mode(self.value)
        if agent is not owner.agent_binding:
            return
        if error is not None:
            owner.app.show_error(error, 'Set Mode')
        elif (mode := agent.current_mode) is not None:
            owner.feedback.flash(Content.from_markup('Mode changed to [b]$mode', mode=mode.name), style='success')


class Conversation(
    AgentTurnEvents,
    FirstPromptTitle,
    ColumnLayout,
    GoalView[GoalSession],
    TranscriptView,
    FollowsLayoutPreferences,
    QueueEvidenceOwner,
    ConversationCommsHandlers,
    NativeMethodKeys,
    ConversationSessionBinding,
    MenuConversation,
    ReadsCommandCatalog,
    AddressesItsThread,
    AgentConversationCommands,
    SourcedConversation,
    BoundViewHost,
    actions=(ConversationAction,),
):
    """Holds the agent conversation (input, output, and various controls / information)."""

    def thread_presented(self, presentation: ThreadPresentation) -> None:
        """A settled member owns whether this view has source work to publish."""
        self.thread_presentation = presentation
        self._update_model_info()
        self.operational_sources.thread_presented(self)
        self.goal_source.presentation_changed(self.goal_observation)
        self.dispatch_sync(presentation)

    def defer_agent_start(self) -> None:
        self.screen.frame_presentation.defer(self, self._start_agent)

    def consumed(self, message: CoreEventMessage) -> None:
        """The conversation handled the agent's publication; it stops bubbling here."""
        message.stop()

    def agent_surface(self, events):
        """Textual receives its agent's events through its message pump and mounts their
        widgets (`AttachedSurfaceBinding`)."""
        return AttachedSurfaceBinding(self, events)

    def keyboard_scopes(self) -> tuple[DeclaredWidgetActions, ...]:
        """The conversation owns its persistent reader and composer key targets."""
        return (self, self.window, self.prompt)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.layers = ("base", "prompt", "float")

    BLANK = True
    MAX_LIVE_BLOCKS = 32
    BINDING_GROUP_TITLE = "Conversation"

    window = getters.query_one(Window)
    cursor = getters.query_one(CursorContainer)

    # ---- BoundViewHost: Textual draws the blocks as mounted children ----

    @property
    def live_blocks(self) -> tuple[Widget, ...]:
        return tuple(self.contents.children)

    def retire_blocks(self, blocks):
        return self.transcript.retire_presentations(self.contents, self.output, blocks)

    def protected_blocks(self, candidates):
        return protected_presentations(candidates, (*self.screen._interaction_widgets(), *self.cursor_block.endpoints))

    def blocks_in_viewport(self, candidates) -> bool:
        # A hidden tab has no exposed viewport. Never request offscreen geometry
        # (which could rebuild the whole scene) to decide retirement.
        if not self.screen.is_current:
            return False
        visible = self.screen._compositor.published_widgets
        viewport = self.window.published_viewport
        return any(widget in visible and viewport.overlaps(visible[widget][0]) for widget in candidates)

    def show_draft(self, draft, identity) -> None:
        DRAFT_PRESENTATION.project_value(draft, self.cli_draft, identity)

    def clear_draft(self) -> None:
        self.cli_draft.clear()

    def empty_history(self, notification_view=None) -> TranscriptHistory:
        return TranscriptHistory.empty(
            view=self,
            notification_view=self.contents if notification_view is None else notification_view,
        )

    def later_history(self, page, source, conversation_order: int) -> TranscriptHistory:
        later = TranscriptHistory(page, source, view=self, notification_view=self.contents,
                                  source_state=LiveTranscript())
        later.conversation_order = conversation_order
        return later

    def mount_history(self, history, *, before=None):
        return self.contents.mount(history, before=before)

    def remove_history(self, history):
        return history.remove()

    def after_refresh(self, callback) -> None:
        self.call_after_refresh(callback)

    def join_completion(self, completion) -> None:
        completion.call_when_ready(self)

    def on_native_pump(self) -> bool:
        return asyncio.current_task() is self.task

    async def native_applied(self) -> bool:
        pump = self.task
        applied = asyncio.get_running_loop().create_future()

        def complete() -> None:
            if not applied.done():
                applied.set_result(None)

        if not self.call_later(complete):
            return False
        try:
            await asyncio.wait((applied, pump), return_when=asyncio.FIRST_COMPLETED)
            return applied.done()
        finally:
            applied.cancel()

    def start_publication(self, task, *, exclusive: bool):
        kind = WindowPublicationWork if exclusive else SourcePublicationWork
        return kind.start(self, task)

    def cancel_publications(self):
        return (*WindowPublicationWork.cancelled_work(self), *SourcePublicationWork.cancelled_work(self))

    def current_publication(self):
        return get_current_worker()

    def view_painted(self) -> None:
        self.retire_loading_splash()
        self.query_ancestor(SessionView).history_painted()

    def refresh_session_summary(self) -> None:
        self.query_one(SessionDetails)._refresh_summary()

    async def present_submission_error(self, detail: str) -> None:
        await self.post(StopReasonNote(INTERNAL_EROR.replace("$ERROR", detail)))

    def painted_read(self, acknowledge: Callable[[TranscriptCursor], PaintedRead]) -> PaintedRead:
        """Decide before constructing a worker or opening a read/write context."""
        if not self.is_mounted or self.visible_categories != all_categories():
            return NothingToRead()
        window = self.window
        if not window.follows_tail:
            return NothingToRead()
        if any(history.blocks_visible_read for history in window.histories):
            return NothingToRead()
        return self.transcript.displayed_cursor.painted_read(acknowledge, NothingToRead())

    def watch_visible_categories(
        self,
        previous: frozenset[type[MessageCategory]],
        selected: frozenset[type[MessageCategory]],
    ) -> None:
        # The reader stays on the message they are reading; when the new
        # selection hides it, on the next message still shown.
        window = self.window
        window.keep_reader()
        self.navigation.clear()
        for block in self.contents.children:
            block.apply_message_filter(selected)
        screen = self.screen
        screen.selections = {
            widget: selection
            for widget, selection in screen.selections.items()
            if all(node.display for node in widget.walk_ancestors(with_self=True))
        }

    def remember_tool_expansion(self, tool_id: str, expanded: bool) -> None:
        """Retain bounded manual disclosure state across canonical transcript remounts."""
        self.tool_expansions.pop(tool_id, None)
        self.tool_expansions[tool_id] = expanded
        if len(self.tool_expansions) > 512:
            del self.tool_expansions[next(iter(self.tool_expansions))]

    @property
    def agent_title(self) -> str:
        return self.query_ancestor(SessionScope).display_name

    def insert_path_into_prompt(self, path: Path) -> None:
        if not path.is_relative_to(self.project_path.path):
            # Paths outside the project have no prompt reference.
            self.app.bell()
            return
        insert_path_text = str(path.relative_to(self.project_path.path))

        insert_text = (
            f'@"{insert_path_text}"'
            if " " in insert_path_text
            else f"@{insert_path_text}"
        )
        self.prompt.prompt_text_area.insert(insert_text)
        self.prompt.prompt_text_area.insert(" ")

    def watch_project_path(self, path: Checkout) -> None:
        self.publish_core(core_events.SessionPathChanged(str(path)))

    async def sync_project_path(self, path: Checkout) -> None:
        """Apply the owner's project to every cwd-bound part of this view."""
        self.project_path = path
        self.working_directory = str(path)
        self.project_data_path = paths.get_project_data(path)
        self.input_histories.bind_project(self.project_data_path)
        if self._shell is not None and not self._shell.is_finished:
            with suppress(TimeoutError):
                async with asyncio.timeout(2):
                    await self._shell.change_directory(str(path))
        await self.agent_binding.project_changed(path.path)

    def sync_working(self) -> None:
        self.throbber_above.sync()

    def _turn_changed(self, owner: TurnOwner) -> None:
        self.sync_working()
        for prompt in self.query(Prompt):
            prompt.sync_turn()
        for details in self.query(OperationalSessionDetails):
            details.sync_turn()
        self.refresh_bindings()

    @on(ObservedThreadActivity.Changed)
    def _observed_activity_changed(self, event: ObservedThreadActivity.Changed) -> None:
        event.stop()
        self.sync_working()
        for prompt in self.query(Prompt):
            prompt.sync_session()

    def starts_typing(self, event: events.Key) -> bool:
        """A key typed in the window that starts a prompt."""
        character = event.character or ""
        return (
            not self.prompt.prompt_text_area.editing_mode.modal
            and event.is_printable
            and (character.isalnum() or character in "$/!")
        )

    def start_typing(self) -> None:
        """Focus moves now, not after the queued keys: the rest of a burst follows it."""
        target = self.prompt.typing_target
        if target is not None:
            self.screen.set_focus(target, scroll_visible=False)

    def retire_loading_splash(self) -> None:
        """The composed splash is consumed once when saved history paints or fails."""
        splashes, self._thread_loading = self._thread_loading, ()
        for splash in splashes:
            splash.remove()

    def compose(self) -> ComposeResult:
        with AgentWindow():
            with ContentsGrid():
                yield CursorContainer()
                with ConversationContents() as contents:
                    yield self.empty_history(contents)
                    yield from self._thread_loading
                    yield self.cli_draft
        yield Flash()
        with PromptStack():
            self.thread_activity = OperationalSessionDetails(
                self,
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
                agent_binding=Conversation.agent_binding,
                model_history_scope=Conversation.model_history_scope,
                status=Conversation.status,
            )
            # A retained editor is installed before Prompt.on_mount can apply a
            # profile. Returning to a tab must not spawn a throwaway Neovim.
            prompt.initial_editing_mode = self.query_ancestor(SourcesScope).initial_editing_mode
            self.goal_bar: GoalBar = GoalBar(self, prompt=prompt)
            yield self.goal_bar
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
        if not event.terminal.is_finalized:
            await self.shell.interrupt()
            self.navigation.clear()
            self.feedback.flash("Command interrupted", style="success")

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
            self.feedback.flash("Press [b]ctrl+f[/b] to focus command", style="default")

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
        self.feedback.flash("Press [b]escape[/b] [i]twice[/] to exit terminal", style="success")

    @on(events.DescendantBlur, "Terminal")
    def on_terminal_blur(self, event: events.DescendantFocus) -> None:
        self.focus_prompt()

    @on(messages.Flash)
    def on_flash(self, event: messages.Flash) -> None:
        event.stop()
        self.feedback.flash(event.content, duration=event.duration, style=event.style)

    @property
    def terminal_action_state(self) -> bool | None:
        return None if self._terminal is None else True

    def focus_terminal(self) -> None:
        if (terminal := self._terminal) is not None:
            terminal.focus()

    async def interrupt_shell(self) -> None:
        """Menu and keyboard interruption share the live terminal's eligibility."""
        if self.terminal_action_state:
            await self.shell.interrupt()
            self.flash_success("Command interrupted")

    @property
    def cursor_block(self) -> ConversationEntry | AbsentEntry:
        return self.navigation.current

    def draws_user_message(self, sent) -> bool:
        return self.transcript.binding.history.draws(sent)

    async def _apply_session_name(self, name: str) -> None:
        await self.agent_binding.set_session_name(name)
        self.publish_core(core_events.SessionTitleChanged(name))

    async def rename_session(self, name: str) -> None:
        """Apply an explicit user- or agent-provided title to this session."""
        self._auto_title_eligible = False
        await self._apply_session_name(name)

    @handles(core_events.SessionInfoUpdate)
    async def on_session_info_update(self, event: core_events.SessionInfoUpdate) -> None:
        self._auto_title_eligible = False
        self.publish_core(core_events.SessionThreadTitle(event.title or ""))

    @handles(AgentFail)
    async def on_agent_fail(self, event: AgentFail) -> None:
        self.retire_loading_splash()
        self.turns.finish_client()
        self._agent_fail = True
        self.prompt.sync_session()
        for details in self.query(OperationalSessionDetails):
            details.sync_turn()
        self.app.show_error(event.message, "Agent failure")

        self.launch.publish_usage(
            self.app.application.usage.publish,
            "agent-session-error",
            message=event.message,
            details=event.details,
        )

        await self.agent_binding.session_disposition.present_failure(
            event, self
        )

    @work
    @handles(input_events.ChangeMode)
    async def on_change_mode(self, event: input_events.ChangeMode) -> None:
        await self.set_mode(RequestedModeId.from_optional(event.mode_id))

    @handles(input_events.ProviderLogin)
    def on_provider_login(self, event: input_events.ProviderLogin, message: CoreEventMessage) -> None:
        message.stop()
        self.provider_login()

    @work(group="provider-login", exclusive=True)
    async def provider_login(self) -> None:
        agent = self.agent_binding
        methods = agent.presentation.auth_methods
        if not methods:
            self.feedback.flash("This agent has not advertised any login methods", style="error")
            return
        method_id = await ContextMenu.choose(
            self.screen,
            self.prompt.region,
            "Connect a provider",
            [(method.id, method.name) for method in methods],
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
                        CatalogCommandAction.bind(
                            "login", Command(method.name, command)
                        ),
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
                async def prepare_login():
                    await self.prune_window(0, 0)
                    self.output.boundary()

                await agent.prepare_login(prepare_login)
                await agent.session.reconnect_after_login()
            else:
                await agent.session.authenticate(method_id)
            self.feedback.flash(
                "Provider login finished; model catalogue refreshed", style="success"
            )
        finally:
            for prompt in self.query(Prompt):
                prompt.disabled = False
                prompt.focus()

    def flash_model_changed(self, model_name: str, thinking: str) -> None:
        self.feedback.flash(
            Content.from_markup(
                "Model [b]$model[/] · thinking [b]$level",
                model=model_name,
                level=thinking,
            ),
            style="success",
        )

    @work
    @handles(ChangeConfiguration)
    async def on_change_configuration(self, event: ChangeConfiguration) -> None:
        await self.apply_configuration_change(event)

    @work
    @handles(ChangeModel)
    async def on_change_model(self, event: ChangeModel) -> None:
        await self.apply_model_change(event)

    @handles(input_events.UserInputSubmitted)
    async def on_user_input_submitted(self, event: input_events.UserInputSubmitted, message: CoreEventMessage) -> None:
        message.stop()
        await self.submissions.received(event)()

    def queue_controls_changed(self) -> None:
        """The composer's delivery controls moved; the goal bar redraws its separators."""
        self.goal_bar._queue_separator_update()

    def before_turn_settle(self) -> None:
        self._agent_activity_boundary.reset()

    async def before_turn_boundary(self) -> None:
        pending_loading, self._loading = self._loading, None
        if pending_loading is not None and pending_loading.is_attached:
            await pending_loading.remove()

    def after_turn_boundary(self) -> None:
        self.check_directory()
        self._turn_count += 1

    async def present_stop_note(self, text: str) -> None:
        await self.post(StopReasonNote(text))

    @on(Menu.OptionSelected)
    async def on_menu_option_selected(self, event: Menu.OptionSelected) -> None:
        event.stop()
        await event.command.run(event.menu)
        self.call_after_refresh(self.cursor.refresh)

    @handles(CurrentWorkingDirectoryChanged)
    def on_current_working_directory_changed(self, event: CurrentWorkingDirectoryChanged) -> None:
        if self._shell is None or self._shell.pending_directory is None:
            self.working_directory = str(Path(event.path).resolve().absolute())

    @on(TerminalTool.Projection)
    async def on_terminal_projection(self, message: TerminalTool.Projection) -> None:
        message.stop()
        await message.binding.present_terminal(message, self)

    @handles(core_events.UpdateStatusLine)
    async def on_update_status_line(self, event: core_events.UpdateStatusLine) -> None:
        # The shared widget can receive a queued status message after its
        # source changes. The selected Agent owns the measured value.
        self.agent_binding.refresh_context(self)

    @handles(core_events.RejectedSessionUpdate)
    async def on_rejected_session_update(self, event: core_events.RejectedSessionUpdate) -> None:
        self.output.boundary()
        await self.post(
            ErrorNote(
                Content.styled("Invalid ACP update rejected", "$text-error"),
            )
        )

    @handles(CursorPresentation)
    def on_private_native_cursor_update(
        self, update: CursorPresentation, message: CoreEventMessage
    ) -> None:
        message.stop()
        if message.event.sequence <= self._private_cursor_sequence:
            return
        self._private_cursor_sequence = message.event.sequence
        self.native_history_status = update.status

    @handles(McpClientAcknowledgementUpdate)
    async def on_mcp_client_status(
        self, update: McpClientAcknowledgementUpdate, message: CoreEventMessage
    ) -> None:
        """Show the MCP server summary only within the active turn it describes."""
        if self._mcp_live_note:
            return  # The package emits at most one server summary per turn.
        rows = update.acknowledgement.servers
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

    async def turn_settled(self) -> None:
        await self._clear_mcp_live()
        self._agent_activity_boundary.reset()

    def goal_changed_from(self, publisher: object) -> None:
        self.goal_observation.invalidate_from(publisher)

    async def present_started_user_input(self, started) -> None:
        await self.post(UserInput(started.text, claim=StartedInputClaim(started)))

    def restore_composer_draft(self, text: str) -> None:
        self.prompt.restore_draft(text)

    def coordination_synced(self) -> None:
        self.prompt.sync_session()
        self.prompt.sync_queue()

    async def present_turn_cancelled(self, feedback: str) -> None:
        await self.post(StopReasonNote(f"## Turn cancelled\n\n{feedback}"))

    async def _clear_mcp_live(self) -> None:
        if self._mcp_live_note is not None:
            await self._mcp_live_note.remove()
            self._mcp_live_note = None

    @handles(core_events.McpClientStopped)
    async def on_mcp_client_stopped(self, event: core_events.McpClientStopped) -> None:
        await self._clear_mcp_live()

    @handles(core_events.Plan)
    async def on_acp_plan(self, event: core_events.Plan) -> None:

        if self.contents.children and isinstance(
            (current_plan := self.contents.children[-1]), ConversationPlan
        ):
            current_plan.entries = event.entries
        else:
            await self.post(ConversationPlan(event.entries))

    async def set_mode(self, mode_id: RequestedModeId) -> None:
        await mode_id.apply_to_conversation(self)

    @handles(input_events.HistoryMove)
    async def on_history_move(self, event: input_events.HistoryMove, message: CoreEventMessage) -> None:
        message.stop()
        history = self.input_histories.history(event.history_kind)
        entry = await history.navigate(event.direction, event.body)
        history.present(self.prompt, entry)

    @work
    async def request_permissions(self, request) -> None:
        await request.present(self)

    def ask(
        self,
        options: list[Answer],
        title: str = "",
        get_content: Callable[[], Widget] | None = None,
        callback: Callable[[Answer], None] | None = None,
    ) -> Ask:
        """Replace the prompt with a dialog to ask a question

        Args:
            question: Question to ask or empty string to omit.
            options: A list of (ANSWER, ANSWER_ID) tuples.
            callback: Optional callable that will be invoked with the result.
        """

        self.agent_info

        if self.agent_title:
            notify_title = f"[{self.agent_title}] {title}"
        else:
            notify_title = title
        notify_message = "\n".join(f" • {option.text}" for option in options)
        self.app.input_attention.notify(
            notify_message, title=notify_title, sound="question"
        )

        ask = Ask(title, options, get_content, callback)
        self.prompt.ask(ask)
        return ask

    def open_dialog(self, spec, callback=None) -> None:
        """Show a structured interactive dialog in the prompt area."""
        title = f"[{self.agent_title}] {spec.title}" if self.agent_title else spec.title
        self.app.input_attention.notify(
            spec.message or spec.title,
            title=title or "Input requested",
            sound="question",
        )
        self.prompt.open_dialog(spec, callback)

    def flash_content(self, text: str) -> Content:
        """As plain content: a `Static` given a string reads markup in it."""
        return Content(text)

    def open_team(self, teammate: str) -> None:
        self.app.push_screen(TeamPage(teammate))

    def focus_model_choice(self) -> None:
        self.prompt.model_switcher.focus()

    async def change_project(self, path: Path) -> None:
        await self.agent_binding.change_project(self, path)

    @property
    def can_compact(self) -> bool:
        return self.turns.owner.can_compact

    @property
    def turn_busy(self) -> bool:
        return self.turns.owner.busy

    def request_compaction(self, instructions: str | None) -> None:
        self.agent_binding.request_compaction(self, instructions)

    def about_markdown(self) -> str:
        return about.render(self.app.coordination_access.connection.location)

    async def post_markdown(self, markdown: str) -> None:
        await self.post(MarkdownNote(markdown))

    async def cancel_agent(self) -> None:
        await self.agent_binding.cancel()

    def close_session(self) -> None:
        if self.screen.id is not None:
            self.app.session_navigation.events.publish(session_requests.SessionClose(self.screen.id))

    def request_new_session(self, prompt: str) -> None:
        self.launch.request_new_session(self.app.session_navigation.events, self.working_directory, prompt)

    def command_target_scope(self) -> CommandTargetScope:
        return self.query_ancestor(CommandTargetScope)

    @work(group="command-catalog", exclusive=True)
    async def update_slash_commands(self) -> None:
        """Prepare choices only for the prompt that can actually paint them.

        Hidden sources keep their display resource and refresh on selection;
        command execution always reacquires current backend applicability.
        """
        if not self.is_attached:
            return
        source = self.query_ancestor(SessionScope)
        if not source.is_current:
            return
        catalog = await self.read_command_catalog()
        if self.is_attached and source.is_current:
            self.prompt.slash_commands = catalog.commands

    def command_navigation(self):
        return self.query_ancestor(NavigationScope).navigation_owner.navigation_context

    @handles(LinkContextChanged)
    async def _command_source_changed(self, event: LinkContextChanged) -> None:
        self.on_composer("refresh_commands", lambda prompt: prompt.slash_complete.refresh_commands())

    @handles(core_events.SessionSelected, core_events.OpenTabsChanged)
    async def _selected_commands_changed(self, event: core_events.SessionSelected | core_events.OpenTabsChanged) -> None:
        self.update_slash_commands()

    def transcript_binding(self) -> ViewBinding:
        """A native session publishes its transcript through this view."""
        return BoundView(self)

    @on(events.Mount)
    async def on_mount(self) -> None:
        self.transcript.bind(self)
        await self.initialize_view()

    def apply_layout_preferences(self) -> None:
        """Project the original settings without retaining their semantic values."""
        self.apply_column_layout()

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
        self.refresh_thread_status()

        self.input_histories.shell.complete.add_words(
            self.app.settings.shell.allow_commands.split()
        )
        self.start_native_session()
        self.window.anchor()

    @handles(core_events.InputDispositionsChanged)
    async def on_input_dispositions_changed(self, event: core_events.InputDispositionsChanged) -> None:
        self.delivery_observation.invalidate()

    async def inspect_session(self) -> None:
        await self.delivery_observation.refresh()
        details = InputDeliveryDetails(
            log_path=self.agent_binding.presentation.log_path,
            load_history=self.delivery_observation.history,
            dismiss_history=self.delivery_observation.dismiss_history,
        )
        # A modal remains a view of the same backend snapshot, including later starts.
        details.delivery = self.input_delivery
        shown = tuple(self.query(OperationalSessionDetails))
        for session_details in shown:
            details.overview_text = session_details.overview_text
        self.app.push_screen(details)
        details.watch(
            self, "input_delivery", lambda state: setattr(details, "delivery", state)
        )
        for session_details in shown:
            details.watch(
                session_details,
                "overview_text",
                lambda value: setattr(details, "overview_text", value),
            )

    @handles(input_events.GoalControlActivated)
    async def on_goal_control(self, event: input_events.GoalControlActivated, message: CoreEventMessage) -> None:
        message.stop()
        await self.goal_controls.activate(event.action)

    @work(group="context-compaction")
    async def compact_context(self, instructions: str | None) -> None:
        """Keep processing owner notifications while compaction is in flight."""
        self.window.anchor()
        self.feedback.flash("Compaction requested")
        await self.agent_binding.compact_context(instructions)
        self.feedback.flash("Context compacted", style="success")

    def queue_evidence_changed(self) -> None:
        self.submissions.publish_pending()

    def open_queue_menu(self) -> None:
        self.app.push_screen(QueueInspection(self.submissions))

    @handles(PreferenceChanged)
    async def _settings_changed(self, event: PreferenceChanged) -> None:
        if SETTINGS.shell.allow_commands.matches(event.field):
            self.input_histories.shell.complete.add_words(
                self.app.settings.shell.allow_commands.split()
            )

    @work
    async def post_welcome(self) -> None:
        """Post any welcome content."""

    @on(events.MouseDown)
    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._mouse_down_offset = event.screen_offset

    @on(events.Click)
    def on_click(self, event: events.Click) -> None:
        # A queued history click may arrive after its logical source retired.
        if not self.is_current_session:
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
        if event.style.meta.get("@click") is not None:
            return
        try:
            widget.query_ancestor(Prompt)
        except NoMatches:
            pass
        else:
            return

        if self.navigation.select(widget):
            self.refresh_block_cursor(lambda cursor: cursor.show_clicked(self.window))

    # ---- TurnPresentation: the shared turn code's blocks, as Textual widgets ----

    @property
    def shows_live_output(self) -> bool:
        return self.is_attached

    def after_live_output(self, finish) -> None:
        self.call_later(finish)

    async def present_user_input(self, text: str) -> None:
        await self.post(UserInput(text))

    def response_block(self, fragment: str, delivery) -> AgentResponse:
        return AgentResponse(fragment, delivery=delivery)

    def thought_block(self, fragment: str) -> AgentThought:
        return AgentThought(fragment)

    async def show_live_block(self, block, stream) -> None:
        await self.post(block, new_block=False)

    async def present_error_note(self, message: str, details: str) -> None:
        if message:
            error = Content.assemble(
                Content.from_markup(message).stylize("$text-error"),
                " — ",
                Content(details.strip()).stylize("dim"),
            )
        else:
            error = Content(details.strip()).stylize("$text-error")
        await self.post(ErrorNote(error))

    async def present_help_note(self, markdown: str) -> None:
        await self.post(MarkdownNote(markdown))

    async def present_log_link(self, markdown: str) -> None:
        await self.post(AgentResponse(markdown, show_divider=False, category=OtherCategory))

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

        blocks = (
            (AgentActivityDivider(widget.message_category, widget), widget)
            if widget.starts_agent_activity(self._agent_activity_boundary)
            else (widget,)
        )
        for block in blocks:
            block.prepare_post(self.transcript)
        await self.contents.mount(*blocks)
        for block in blocks:
            await block.posted(self.transcript)

        widget.loading = loading
        self._require_check_prune = True
        self.call_after_refresh(self.check_prune)
        return widget

    async def check_prune(self) -> None:
        """Check if a prune is required."""
        if self._require_check_prune:
            self._require_check_prune = False
            low_mark = self.settings.ui.prune_low_mark
            high_mark = low_mark + self.settings.ui.prune_excess
            if self.transcript.readable:
                # Height pressure is not source evidence. Dropping the source
                # pager or an uncovered wire claim lets a later observation
                # recreate the same record as a new tail arrival.
                # Saved pages already have a bounded preparation owner. Only
                # the native tail consumes the live-block pressure allowance.
                live_height = (self.contents.virtual_size.height
                               - self.transcript.binding.history.outer_size.height)
                if live_height > high_mark:
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

    async def new_terminal(self) -> ShellTerminal:
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
            name=f"terminal #{self._terminal_count}",
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
                shell_directory,
                terminal_size=self.get_terminal_dimensions(),
                shell=shell_command,
                start=shell_start,
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

    def move_cursor(self, direction: CursorDirection) -> None:
        self.navigation.move(direction)
        self.refresh_block_cursor(lambda cursor: cursor.show_moved_to(self.window))


    @work
    async def cancel_turn(self, shortcut: str) -> None:
        if monotonic() - self._last_escape_time < 3:
            await self.agent_binding.cancel_turn(self)
            self._last_escape_time = 0.0
        else:
            self.feedback.flash(f"Press [b]{shortcut}[/] again to cancel agent's turn")
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
        self.transcript.binding.request(self.transcript)


    async def select_block(self) -> None:
        cursor = self.navigation.cursor
        for block in cursor.selected_widgets:
            commands = Menu.block_commands(cursor, cursor.get_block_menu())
            menu = Menu(self, block, commands, focus_owner=self.window)
            menu.offset = Offset(1, cursor.region.top(self.window.region.y))
            await self.mount(menu)
            menu.focus()

    def block_clipboard_text(self) -> str:
        return self.navigation.cursor.get_clipboard_text()

    def block_prompt_text(self) -> str:
        return self.navigation.cursor.get_prompt_text()

    def append_to_prompt(self, text: str) -> None:
        self.prompt.append(text)
        self.focus_prompt()

    def maximize_block(self) -> None:
        cursor = self.navigation.cursor
        if cursor.allow_maximize:
            cursor.maximize(self.screen)

    def export_block_to_svg(self) -> None:
        self.navigation.cursor.export_to_svg(self)

    def open_render_as_svg(self, size: Size, render: object) -> None:
        width, height = size
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
        self.app.open_url(f"file:///{svg_path}")

    def refresh_block_cursor(self, show: Callable[[BlockCursor], None]) -> None:
        """Paint the cursor's new block; `show` scrolls for how the cursor got there."""
        self.cursor.refresh()
        self.navigation.cursor.present(self, show)
        self.refresh_bindings()

    def _present_block_cursor(
        self, cursor: BlockCursor, show: Callable[[BlockCursor], None]
    ) -> None:
        # A later prompt, tab or source event may already have moved the cursor
        # off this block.
        if (
            self.is_attached
            and not self.is_leaving
            and self.is_current_session
            and self.navigation.cursor is cursor
        ):
            show(cursor)
            self.cursor.refresh()
            self.refresh_bindings()
