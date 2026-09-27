"""Visible controls for the server-owned persistent thread goal."""

from typing import ClassVar

from agent_comms import Goal, GoalExecution, GoalExecutionState
from rich.cells import cell_len
from textual import events
from textual.app import ComposeResult, ScreenStackError, UnknownModeError
from textual.binding import BindingType
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.message import Message
from textual.reactive import var
from textual.widgets import Static

from toad.widgets.goal_text import GoalText


class GoalControl(Static, can_focus=True):
    BINDINGS: ClassVar[list[BindingType]] = [("enter,space", "activate", "Select")]
    DEFAULT_CSS = """
    GoalControl { width: auto; height: 1; margin-right: 2; color: $text-secondary; pointer: pointer; }
    GoalControl:hover, GoalControl:focus { text-style: underline; }
    """

    class Activated(Message):
        def __init__(self, action: str):
            super().__init__()
            self.action = action

    def action_activate(self):
        if not self.disabled:
            self.post_message(self.Activated(self.id or ""))

    def on_click(self, event: events.Click):
        event.stop()
        self.action_activate()


class StandbyPulse(Static):
    """A quiet wait animation; the backend decides when it is active."""

    DEFAULT_CSS = "StandbyPulse { width: 2; height: 1; color: $text-muted; }"
    active: var[bool] = var(False)
    _dim = False

    def watch_active(self) -> None:
        self.auto_refresh = 0.8 if self.active else None
        self.update("◌" if self.active else "")

    def automatic_refresh(self) -> None:
        if not self.active or not self.is_attached:
            return
        try:
            screen = self.screen
            if (
                screen is not self.app.screen
                or self not in screen._compositor.visible_widgets
            ):
                return
        except ScreenStackError, UnknownModeError:
            return
        self._dim = not self._dim
        self.styles.opacity = 0.45 if self._dim else 1.0


class GoalBar(VerticalGroup):
    DEFAULT_CSS = """
    GoalBar { height: auto; padding: 0 1; border-top: solid $secondary 30%; }
    GoalBar .goal-header { height: auto; }
    GoalBar .goal-document { height: 1; max-height: 50vh; scrollbar-gutter: stable; }
    GoalBar .goal-summary { height: auto; }
    GoalBar .goal-progress { height: auto; color: $text-muted; }
    GoalBar .goal-execution-row { height: auto; }
    GoalBar .goal-execution { width: 1fr; height: auto; }
    GoalBar .goal-controls { height: 1; grid-rows: 1; }
    GoalBar.-collapsed GoalControl { margin-right: 1; }
    GoalBar.-resize-hover, GoalBar.-resizing { border-top: solid white; pointer: ns-resize; }
    """
    goal: var[Goal | None] = var(None)
    execution: var[GoalExecution | None] = var(None)
    unavailable: var[bool] = var(False)
    collapsed: var[bool] = var(False)
    _separator_update_pending = False
    _throbber = None
    _prompt = None
    _document_height: int | None = None
    _resize_origin: tuple[int, int] | None = None

    def on_mount(self) -> None:
        from toad.widgets.prompt import Prompt
        from toad.widgets.throbber import Throbber

        # Observe the existing presentation owners instead of introducing a
        # second definition of "running" or "queue mode" on Conversation.
        self._throbber = self.parent.query_one_optional(Throbber)
        self._prompt = self.parent.query_one_optional(Prompt)
        if self._throbber is not None:
            self.watch(self._throbber, "busy", self._queue_separator_update)
        if self._prompt is not None:
            self.watch(self._prompt, "turn", self._queue_separator_update)
            self.watch(self._prompt, "queue_supported", self._queue_separator_update)
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
        controls = (
            self._prompt.query_one_optional(".delivery-controls")
            if self._prompt
            else None
        )
        loading = (
            throbber is not None
            and throbber.busy
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
            yield GoalControl("History", id="goal-history")
            yield GoalControl("Collapse", id="goal-collapse")
            yield GoalControl("Pause", id="goal-toggle")
            yield GoalControl("Edit", id="goal-edit")
            yield GoalControl("Clear", id="goal-clear")

    def on_goal_control_activated(self, event: GoalControl.Activated) -> None:
        if event.action == "goal-collapse":
            event.stop()
            self.collapsed = not self.collapsed

    def watch_collapsed(self) -> None:
        self.set_class(self.collapsed, "-collapsed")
        if self.collapsed:
            self._end_resize()
        if self.is_attached:
            self.query_one("#goal-collapse", GoalControl).update(
                "Expand" if self.collapsed else "Collapse"
            )
            self._update_goal_text()

    def watch_goal(self, goal: Goal | None):
        if goal is None:
            self._end_resize()
        self.display = goal is not None or self.unavailable
        self._update_goal_text()
        if goal is not None:
            progress = self.query_one(".goal-progress", GoalText)
            progress.update_goal_text(
                f"Progress: {goal.progress}" if goal.progress else ""
            )
            progress.display = bool(goal.progress)
            toggle = self.query_one("#goal-toggle", Static)
            toggle.update(goal.toggle_label)
            toggle.display = goal.status != "completed"
            self._update_control_layout()

    def watch_unavailable(self) -> None:
        self.display = self.goal is not None or self.unavailable
        self._update_goal_text()

    def watch_execution(self) -> None:
        self._update_goal_text()

    def _update_goal_text(self) -> None:
        if not self.is_attached:
            return
        header = self.query_one(".goal-header", Static)
        if self.unavailable:
            header.update(
                "Goal state unavailable · last confirmed goal below"
                if self.goal
                else "Goal state unavailable · reconnecting to owner"
            )
        elif self.goal is not None:
            header.update(f"Goal · {self.goal.status} · rev {self.goal.revision}")
        for control in self.query(GoalControl):
            control.disabled = self.unavailable and control.id != "goal-collapse"
        self.query_one(".goal-document").display = self.goal is not None and not self.collapsed
        if self.goal is not None:
            self.query_one(".goal-summary", GoalText).update_goal_text(
                f"Objective: {self.goal.text}"
            )
        execution = self.execution
        standby = (
            not self.unavailable
            and self.goal is not None
            and self.goal.active
            and execution is not None
            and execution.goal_id == self.goal.id
            and execution.state is GoalExecutionState.STANDBY
        )
        if standby:
            header.update(f"Goal · Standby · rev {self.goal.revision}")
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
        if event.button != 1 or self.collapsed or self.goal is None or not self.display:
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
                not self.collapsed and self.goal is not None
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
            controls.styles.layout = "horizontal"
            controls.styles.height = 1
        else:
            # Keep every action reachable in narrow conversation panes.
            columns = len(widths)
            while columns > 1 and sum(max(widths[i::columns]) for i in range(columns)) > width:
                columns -= 1
            controls.styles.layout = "grid"
            controls.styles.grid_size_columns = columns
            controls.styles.grid_columns = " ".join(
                str(max(widths[i::columns])) for i in range(columns)
            )
            controls.styles.height = (len(widths) + columns - 1) // columns

    def update_document_height(self) -> None:
        # Conversation resize also reaches an absent goal or an outage header
        # without a document. Querying that hidden document's geometry forces
        # a full compositor map after the visible viewport was already laid out.
        if self.is_attached and self.display and self.goal is not None and not self.collapsed:
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
