"""Visible controls for the server-owned persistent thread goal."""

from typing import ClassVar
from weakref import ref

from rich.cells import cell_len
from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.layouts.horizontal import HorizontalLayout
from textual.layouts.grid import GridLayout
from textual.reactive import var
from textual.strip import Strip
from ui_theme.effects import STANDBY_PULSE
from textual.widgets import Static
from textual.widget import PrimaryActivation

from toad.goal_interaction import GoalInteraction
from toad.core.input_events import GoalControlActivated
from toad.core_event_carrier import CoreEventReceiver
from toad.widgets.goal_text import GoalText
from toad.textual_colours import Animated


class GoalControl(PrimaryActivation, CoreEventReceiver, Static, can_focus=True):
    BINDINGS: ClassVar[list[BindingType]] = [("enter,space", "activate", "Select")]
    DEFAULT_CSS = """
    GoalControl { width: auto; height: 1; margin-right: 2; color: $text-secondary; pointer: pointer; }
    GoalControl:hover, GoalControl:focus { text-style: underline; }
    """

    @property
    def primary_activation(self):
        return self.action_activate

    def action_activate(self):
        if not self.disabled:
            self.publish_core(GoalControlActivated(GoalInteraction.decode(self.id.removeprefix("goal-"))))

    def on_click(self, event: events.Click):
        event.stop()
        self.action_activate()


class StandbyPulse(Animated, Static):
    """A goal's standby marker; its existing clock owns time and visibility."""

    DEFAULT_CSS = "StandbyPulse { width: 2; height: 1; }"
    active: var[bool] = var(False)

    def on_mount(self) -> None:
        self.watch_active()

    def watch_active(self) -> None:
        if self.active and self.is_mounted:
            if self.animation is None:
                self.run_effect(STANDBY_PULSE)
        else:
            self.stop_effect()
        self.update("◌" if self.active else "")

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if self.active:
            frame = self.animation.frame() if self.animation is not None else STANDBY_PULSE.final
            return frame.paint(self.app.colours, strip)
        return strip


class GoalBar(VerticalGroup):
    DEFAULT_CSS = """
    GoalBar { height: auto; padding: 0 1; border-top: solid $secondary; }
    GoalBar .goal-header { height: auto; }
    GoalBar .goal-document { height: 1; max-height: 50vh; scrollbar-gutter: stable; }
    GoalBar .goal-summary { height: auto; }
    GoalBar .goal-progress { height: auto; color: $text-muted; }
    GoalBar .goal-execution-row { height: auto; }
    GoalBar .goal-execution { width: 1fr; height: auto; }
    GoalBar .goal-controls { height: 1; grid-rows: 1; }
    GoalBar.-collapsed GoalControl { margin-right: 1; }
    GoalBar.-resize-hover, GoalBar.-resizing { border-top: solid $foreground; pointer: ns-resize; }
    """
    collapsed: var[bool] = var(False)
    _separator_update_pending = False
    _document_height: int | None = None
    _resize_origin: tuple[int, int] | None = None

    def __init__(self, source, *, throbber, prompt):
        super().__init__()
        self._source = ref(source)
        self._throbber = throbber
        self._prompt = prompt
        self._horizontal_layout = HorizontalLayout()
        self._grid_layout = GridLayout()

    @property
    def goal_display(self):
        return self._source().goal_display

    @property
    def execution(self):
        return self._source().goal_execution

    def on_mount(self) -> None:
        self.watch(self._source(), "goal_display", self.watch_goal_display)
        self.watch(self._source(), "goal_execution", self.watch_execution)
        self.watch(self._throbber, "busy", self._queue_separator_update)
        self._queue_separator_update()

    def notify_style_update(self) -> None:
        super().notify_style_update()
        if self.is_mounted:
            self._queue_separator_update()

    def _queue_separator_update(self) -> None:
        if not self._separator_update_pending:
            self._separator_update_pending = True
            # Prompt's own watchers first resolve the delivery-controls CSS.
            # Coalesce state changes in this message turn; no timing delay.
            self.call_later(self._update_separators)

    def _update_separators(self) -> None:
        self._separator_update_pending = False
        throbber = self._throbber
        controls = self._prompt.query_one_optional(".delivery-controls")
        loading = (
            throbber.busy
            and throbber.display
            and throbber.visible
        )
        queue_visible = controls is not None and controls.display and controls.visible
        # Reuse the theme-resolved separator; only these local box edges change.
        self.styles.border_top = ("none", "transparent") if loading else None
        self.styles.border_bottom = (
            self.styles.base.border_top if queue_visible else None
        )
        self._update_goal_text()

    def compose(self) -> ComposeResult:
        yield Static("", markup=False, classes="goal-header")
        with HorizontalGroup(classes="goal-execution-row"):
            yield StandbyPulse()
            yield GoalText(classes="goal-execution")
        with VerticalScroll(classes="goal-document"):
            yield GoalText(classes="goal-summary")
            yield GoalText(classes="goal-progress")
        with HorizontalGroup(classes="goal-controls"):
            for action in GoalInteraction.members_with(GoalInteraction):
                yield GoalControl(action.label, id=action.control_id())

    def watch_collapsed(self) -> None:
        self.set_class(self.collapsed, "-collapsed")
        if self.collapsed:
            self._end_resize()
        if self.is_attached:
            self._update_goal_text()

    def watch_goal_display(self) -> None:
        goal = self.goal_display.snapshot
        if goal is None:
            self._end_resize()
        self.display = self.goal_display.visible
        self._update_goal_text()
        if goal is not None and self.is_attached:
            progress = self.query_one(".goal-progress", GoalText)
            progress.update_goal_text(f"Progress: {goal.progress}" if goal.progress else "")
            progress.display = bool(goal.progress)
            self._update_control_layout()

    def watch_execution(self) -> None:
        self._update_goal_text()

    def _update_goal_text(self) -> None:
        if not self.is_attached:
            return
        header = self.query_one(".goal-header", Static)
        state = self.goal_display
        goal = state.snapshot
        execution = self.execution
        header.update(state.heading(execution))
        for action in GoalInteraction.members_with(GoalInteraction):
            control = self.query_one(f"#{action.control_id()}", GoalControl)
            control.disabled = not action.enabled(state)
            control.display = action.visible(state)
            control.update(action.caption(state, self.collapsed))
        self.query_one(".goal-document").display = goal is not None and not self.collapsed
        if goal is not None:
            self.query_one(".goal-summary", GoalText).update_goal_text(f"Objective: {goal.text}")
        standby = state.standby(execution)
        self.query_one(".goal-execution-row").display = standby and not self.collapsed
        self.query_one(StandbyPulse).active = standby and not self.collapsed
        status = self.query_one(".goal-execution", GoalText)
        status.display = standby
        if standby:
            status.update_goal_text(execution.presentation("").summary)
        self._update_control_layout()
        self.call_after_refresh(self.update_document_height)

    def on_resize(self) -> None:
        self._update_control_layout()
        self.call_after_refresh(self.update_document_height)

    def begin_separator_resize(self, event: events.MouseDown) -> None:
        if event.button != 1 or self.collapsed or self.goal_display.snapshot is None or not self.display:
            return
        throbber = self._throbber
        own_edge = bool(self.styles.border_top[0]) and event.screen_y == self.region.y
        loading_edge = (
            throbber is not None and throbber.busy and throbber.display and throbber.visible
            and throbber.region.contains(event.screen_x, event.screen_y)
        )
        if own_edge or loading_edge:
            event.stop()
            self._resize_origin = (event.screen_y, self.query_one(".goal-document").region.height)
            self.set_class(True, "-resizing")
            self.capture_mouse()

    def _drag_resize(self, screen_y: int) -> None:
        if self._resize_origin is not None:
            start_y, start_height = self._resize_origin
            self._document_height = max(
                1, min(self.screen.size.height // 2, start_height + start_y - screen_y)
            )
            self.update_document_height()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._resize_origin is not None:
            event.stop()
            self._drag_resize(event.screen_y)
        else:
            self.set_class(
                not self.collapsed and self.goal_display.snapshot is not None
                and bool(self.styles.border_top[0]) and event.screen_y == self.region.y,
                "-resize-hover",
            )

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if event.button == 1 and self._resize_origin is not None:
            event.stop()
            self._drag_resize(event.screen_y)
            self._end_resize()

    def on_leave(self) -> None:
        self.remove_class("-resize-hover")

    def on_unmount(self) -> None:
        self._end_resize()

    def _end_resize(self) -> None:
        if self._resize_origin is not None:
            self._resize_origin = None
            self.release_mouse()
        self.remove_class("-resize-hover", "-resizing")

    def _update_control_layout(self) -> None:
        if not self.is_attached or not self.display or not self.content_size.width:
            return
        controls = self.query_one(".goal-controls")
        widths = [
            cell_len(str(control.render())) + control.styles.margin.width
            for control in controls.query(GoalControl) if control.display
        ]
        width = self.content_size.width
        header_width = cell_len(str(self.query_one(".goal-header", Static).render()))
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
        # Conversation resize also reaches an absent goal or an outage header
        # without a document. Querying that hidden document's geometry forces
        # a full compositor map after the visible viewport was already laid out.
        if self.is_attached and self.display and self.goal_display.snapshot is not None and not self.collapsed:
            document = self.query_one(".goal-document", VerticalScroll)
            width = document.content_size.width
            height = (
                sum(
                    child.visual.get_height(child.styles, width)
                    for child in document.query(GoalText)
                    if child.display
                )
                if width
                else 1
            )
            # Explicit bounded height prevents an auto-height parent from reserving
            # the scroll document's full virtual height before applying its cap.
            limit = (
                self.screen.size.height // 5 if self._document_height is None
                else min(self._document_height, self.screen.size.height // 2)
            )
            document.styles.height = min(max(1, height), max(1, limit))
