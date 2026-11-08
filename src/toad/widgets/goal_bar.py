"""Visible controls for the server-owned persistent thread goal."""

from typing import ClassVar
from weakref import ref

from rich.cells import cell_len
from textual import events
from textual.widget import Widget
from toad.widget_actions import VisibleActions, Activates
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.layouts.horizontal import HorizontalLayout
from textual.layouts.grid import GridLayout
from textual.reactive import var
from textual._paint_state import PaintState
from textual.css.native import ThemeState, DeclaresTheme, Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.strip import Strip
from ui_theme.effects import STANDBY_PULSE, Mix
from ui_theme.scheme import ForegroundColour, SecondaryColour
from textual.widgets import Static

from toad.goal_interaction import GoalInteraction
from toad.goal_view import GoalCollapse
from toad.widgets.prompt import DeliveryControls
from toad.core.input_events import GoalControlActivated
from toad.core_event_carrier import CoreEventReceiver
from toad.widgets.goal_text import GoalText
from toad.frame_presentation import Animated
from toad.native_style import (
    AutoWidth,
    ComposedWhenShown,
    FillWidth,
    MutedText,
    OneRow,
    PointerCursor,
    SecondaryText,
    SidePadding,
    StableGutter,
)
from toad.widgets.selection import ChangingText, InlineSelection
from textual import on


class GoalControl(
    SecondaryText,
    AutoWidth,
    OneRow,
    PointerCursor,
    VisibleActions,
    Activates,
    InlineSelection,
    CoreEventReceiver,
    Static,
    can_focus=True,
):


    def __init__(self, interaction: type[GoalInteraction]):
        super().__init__(interaction.label)
        self.interaction = interaction

    def activate(self):
        if not self.disabled:
            self.publish_core(GoalControlActivated(self.interaction))

class StandbyPulse(OneRow, Animated[Mix], Static):
    """A goal's standby marker; its existing clock owns time and visibility."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = 2
    active: var[bool] = var(False)

    @on(events.Mount)
    def on_mount(self) -> None:
        self.watch_active()

    def watch_active(self) -> None:
        if self.active and self.is_mounted:
            if STANDBY_PULSE not in self.effects:
                self.run_effect(STANDBY_PULSE)
        else:
            self.stop_effect(STANDBY_PULSE)
        self.update("◌" if self.active else "")

    def render_line(self, y: int, paint: PaintState) -> Strip:
        strip = super().render_line(y, paint)
        if self.active:
            frame = self.effect_frame(STANDBY_PULSE)
            return frame.paint(self.app.colours, strip)
        return strip


class GoalProgress(MutedText, GoalText):
    """Its look is its bases."""


class GoalExecutionText(FillWidth, GoalText):
    """Its look is its bases."""


class GoalDocument(StableGutter, OneRow, VerticalScroll):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = "50vh"


class GoalControls(OneRow, HorizontalGroup):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.grid_rows = "1"


class GoalEdge(DeclaresTheme):
    """The bar's top edge at rest: the separator above the goal."""

    native_theme: ClassVar[tuple[NativeDeclaration, ...]] = (
        NativeDeclaration.of(Styles.border_top, Keyword("solid"), Variable(SecondaryColour.name)),
        NativeDeclaration.of(Styles.pointer, Keyword("default")),
    )


class GrabbedGoalEdge(GoalEdge):
    """The edge under the pointer or being dragged resizes the goal document."""

    native_theme = (
        NativeDeclaration.of(Styles.border_top, Keyword("solid"), Variable(ForegroundColour.name)),
        NativeDeclaration.of(Styles.pointer, Keyword("ns-resize")),
    )


class GoalBar(GoalCollapse, ComposedWhenShown, SidePadding, VerticalGroup):
    collapsed: var[bool] = var(False)
    edge = ThemeState(GoalEdge)
    _separator_update_pending = False
    _document_height: int | None = None
    _resize_origin: tuple[int, int] | None = None


    def __init__(self, source, *, prompt):
        super().__init__()
        self._source = ref(source)
        self._prompt = prompt
        self._horizontal_layout = HorizontalLayout()
        self._grid_layout = GridLayout()
        self.header: ChangingText = ChangingText("", markup=False)
        self.pulse: StandbyPulse = StandbyPulse()
        self.execution_text: GoalText = GoalExecutionText()
        self.execution_row: HorizontalGroup = HorizontalGroup(self.pulse, self.execution_text)
        self.summary: GoalText = GoalText()
        self.progress: GoalText = GoalProgress()
        self.document: VerticalScroll = GoalDocument(self.summary, self.progress)
        self.actions: tuple[GoalControl, ...] = tuple(
            GoalControl(action) for action in GoalInteraction.members_with(GoalInteraction)
        )
        self.controls: HorizontalGroup = GoalControls(*self.actions)

    @property
    def goal_display(self):
        return self._source().goal_display

    @property
    def execution(self):
        return self._source().goal_execution

    @on(events.Mount)
    def on_mount(self) -> None:
        self.watch(self._source(), "goal_display", self.watch_goal_display)
        self.watch(self._source(), "goal_execution", self.watch_execution)
        self._queue_separator_update()

    def notify_style_update(self) -> None:
        super().notify_style_update()
        if self.is_mounted:
            self._queue_separator_update()

    def _queue_separator_update(self) -> None:
        if not self._separator_update_pending:
            self._separator_update_pending = True
            # Prompt's own watchers first resolve the delivery controls' display.
            # Coalesce state changes in this message turn; no timing delay.
            self.call_later(self._update_separators)

    def _update_separators(self) -> None:
        self._separator_update_pending = False
        controls = self._prompt.query_one_optional(DeliveryControls)
        queue_visible = controls is not None and controls.display and controls.visible
        # Reuse the theme-resolved separator; only this local box edge changes.
        self.styles.border_bottom = (
            self.styles.border_top if queue_visible else None
        )

    def shown_children(self) -> tuple[Widget, ...]:
        return self.header, self.execution_row, self.document, self.controls

    def watch_collapsed(self) -> None:
        # A collapsed bar packs its controls closer; the bar's state owns their gap.
        for control in self.actions:
            control.styles.margin = (0, 1 if self.collapsed else 2, 0, 0)
        if self.collapsed:
            self._end_resize()
        self._show_state()

    def watch_goal_display(self) -> None:
        """The goal's own text is parsed here only: an execution or collapse change never re-reads it."""
        goal = self.goal_display.snapshot
        self.show(self.goal_display.visible)
        if not self.goal_display.visible:
            self._end_resize()
        if self.is_attached:
            self.summary.update_goal_text(f"Objective: {goal.objective}")
            self.progress.update_goal_text(f"Progress: {goal.progress}")
            self.progress.display = goal.shows_progress
        self._show_state()

    def watch_execution(self) -> None:
        self._show_state()

    def _show_state(self) -> None:
        """What depends on the goal, its execution and the collapse together; the goal's text does not."""
        if not self.is_attached:
            return
        state = self.goal_display
        goal = state.snapshot
        execution = self.execution
        self.header.update(state.heading(execution))
        session = self._source().goal_controls
        for control in self.actions:
            action = control.interaction
            control.disabled = not action.enabled(session)
            control.display = action.visible(session)
            control.update(action.caption(session, self.collapsed))
        self.document.display = goal.shows_document and not self.collapsed
        standby = state.standby(execution)
        self.execution_row.display = standby and not self.collapsed
        self.pulse.active = standby and not self.collapsed
        self.execution_text.display = standby
        if standby:
            self.execution_text.update_goal_text(execution.presentation("").summary)
        self._update_control_layout()
        self.call_after_refresh(self.update_document_height)

    @on(events.Resize)
    def on_resize(self) -> None:
        self._update_control_layout()
        self.call_after_refresh(self.update_document_height)

    @on(events.MouseDown)
    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1 or self.collapsed or not self.goal_display.visible or not self.goal_display.snapshot.shows_document:
            return
        if bool(self.styles.border_top[0]) and event.screen_y == self.region.y:
            event.stop()
            self._resize_origin = (event.screen_y, self.document.region.height)
            self.edge = GrabbedGoalEdge
            self.capture_mouse()

    def _drag_resize(self, screen_y: int) -> None:
        if self._resize_origin is not None:
            start_y, start_height = self._resize_origin
            self._document_height = max(
                1, min(self.screen.size.height // 2, start_height + start_y - screen_y)
            )
            self.update_document_height()

    @on(events.MouseMove)
    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._resize_origin is not None:
            event.stop()
            self._drag_resize(event.screen_y)
        else:
            self.edge = (GoalEdge, GrabbedGoalEdge)[
                not self.collapsed and self.goal_display.snapshot.shows_document
                and bool(self.styles.border_top[0]) and event.screen_y == self.region.y
            ]

    @on(events.MouseUp)
    def on_mouse_up(self, event: events.MouseUp) -> None:
        if event.button == 1 and self._resize_origin is not None:
            event.stop()
            self._drag_resize(event.screen_y)
            self._end_resize()

    @on(events.Leave)
    def on_leave(self) -> None:
        self.edge = (GoalEdge, GrabbedGoalEdge)[self._resize_origin is not None]

    @on(events.Unmount)
    def on_unmount(self) -> None:
        self._end_resize()

    def _end_resize(self) -> None:
        if self._resize_origin is not None:
            self._resize_origin = None
            self.release_mouse()
        self.edge = GoalEdge

    def _update_control_layout(self) -> None:
        if not self.is_attached or not self.goal_display.visible or not self.content_size.width:
            return
        controls = self.controls
        widths = [
            cell_len(str(control.render())) + control.styles.margin.width
            for control in self.actions if control.display
        ]
        width = self.content_size.width
        header_width = cell_len(str(self.header.render()))
        inline = self.collapsed and sum(widths) + header_width <= width
        controls.styles.dock = "left" if inline else "top" if self.collapsed else "none"
        controls.styles.width = "auto" if inline else "1fr"
        if sum(widths) <= width:
            controls.styles.layout = self._horizontal_layout
            controls.styles.height = 1
        else:
            # Keep every action reachable in narrow conversation panes.
            columns = len(widths)
            while columns > 1 and sum(max(widths[i::columns]) for i in range(columns)) > width:
                columns -= 1
            controls.styles.layout = self._grid_layout
            controls.styles.grid_size_columns = columns
            controls.styles.grid_columns = " ".join(
                str(max(widths[i::columns])) for i in range(columns)
            )
            controls.styles.height = (len(widths) + columns - 1) // columns

    def update_document_height(self) -> None:
        # An absent goal or an outage header has no document. Querying that
        # hidden geometry forces a full compositor map after the visible
        # viewport was already laid out.
        if self.is_attached and self.goal_display.snapshot.shows_document and not self.collapsed:
            document = self.document
            width = document.content_size.width
            height = (
                sum(
                    child.visual.get_height(child.text_format, width)
                    for child in (self.summary, self.progress)
                    if child.display
                )
                if width
                else 1
            )
            # Explicit bounded height prevents an auto-height parent from reserving
            # the scroll document's full virtual height before applying its cap.
            # Native viewport units reapply the cap even if this bar's own
            # size does not change when the screen resizes.
            document.styles.max_height = "20vh" if self._document_height is None else "50vh"
            limit = height if self._document_height is None else self._document_height
            document.styles.height = min(max(1, height), max(1, limit))
