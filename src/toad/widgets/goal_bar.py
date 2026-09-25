"""Visible controls for the server-owned persistent thread goal."""

from agent_comms import Goal, GoalExecution, GoalExecutionState
from textual import events
from textual.app import ComposeResult, ScreenStackError, UnknownModeError
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.message import Message
from textual.reactive import var
from textual.widgets import Static

from toad.widgets.goal_text import GoalText


class GoalControl(Static, can_focus=True):
    BINDINGS = [("enter,space", "activate", "Select")]
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
    GoalBar .goal-document { height: 1; max-height: 20vh; scrollbar-gutter: stable; }
    GoalBar .goal-summary { height: auto; }
    GoalBar .goal-progress { height: auto; color: $text-muted; }
    GoalBar .goal-execution-row { height: auto; }
    GoalBar .goal-execution { width: 1fr; height: auto; }
    GoalBar .goal-scroll-hint { height: 1; color: $text-muted; }
    """
    goal: var[Goal | None] = var(None)
    execution: var[GoalExecution | None] = var(None)
    unavailable: var[bool] = var(False)
    _separator_update_pending = False
    _throbber = None
    _prompt = None

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
        yield Static(
            "Scroll for full text · Expand",
            markup=False,
            classes="goal-scroll-hint",
        )
        with HorizontalGroup():
            yield GoalControl("Expand", id="goal-expand")
            yield GoalControl("Pause", id="goal-toggle")
            yield GoalControl("Edit", id="goal-edit")
            yield GoalControl("Clear", id="goal-clear")

    def watch_goal(self, goal: Goal | None):
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
            control.disabled = self.unavailable
        self.query_one(".goal-document").display = self.goal is not None
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
        self.query_one(".goal-execution-row").display = standby
        self.query_one(StandbyPulse).active = standby
        status = self.query_one(".goal-execution", GoalText)
        status.display = standby
        if standby:
            status.update_goal_text(execution.presentation("").summary)
        self.call_after_refresh(self._update_scroll_hint)

    def on_resize(self) -> None:
        self.call_after_refresh(self._update_scroll_hint)

    def _update_scroll_hint(self) -> None:
        if self.is_attached:
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
            document.styles.height = min(
                max(1, height), max(1, self.screen.size.height // 5)
            )
            self.query_one(".goal-scroll-hint").display = (
                self.goal is not None and height > document.styles.height.value
            )
