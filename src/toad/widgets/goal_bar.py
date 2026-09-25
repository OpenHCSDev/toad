"""Visible controls for the server-owned persistent thread goal."""

from agent_comms import Goal, GoalExecution, GoalExecutionState
from textual import events
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup
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
        self.post_message(self.Activated(self.id or ""))

    def on_click(self, event: events.Click):
        event.stop()
        self.action_activate()


class GoalBar(VerticalGroup):
    DEFAULT_CSS = """
    GoalBar { height: auto; padding: 0 1; border-top: solid $secondary 30%; }
    GoalBar .goal-summary { height: auto; max-height: 3; }
    GoalBar .goal-progress { height: auto; max-height: 2; color: $text-muted; }
    """
    goal: var[Goal | None] = var(None)
    execution: var[GoalExecution | None] = var(None)
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
        yield GoalText(classes="goal-summary")
        yield GoalText(classes="goal-execution")
        yield GoalText(classes="goal-progress")
        with HorizontalGroup():
            yield GoalControl("Expand", id="goal-expand")
            yield GoalControl("Pause", id="goal-toggle")
            yield GoalControl("Edit", id="goal-edit")
            yield GoalControl("Clear", id="goal-clear")

    def watch_goal(self, goal: Goal | None):
        self.display = goal is not None
        if goal is not None:
            self._update_goal_text()
            progress = self.query_one(".goal-progress", GoalText)
            progress.update_goal_text(goal.progress)
            progress.display = bool(goal.progress)
            toggle = self.query_one("#goal-toggle", Static)
            toggle.update(goal.toggle_label)
            toggle.display = goal.status != "completed"

    def watch_execution(self) -> None:
        self._update_goal_text()

    def _update_goal_text(self) -> None:
        if not self.is_mounted or self.goal is None:
            return
        self.query_one(".goal-summary", GoalText).update_goal_text(self.goal.summary)
        status = self.query_one(".goal-execution", GoalText)
        execution = self.execution
        standby = (
            execution is not None
            and self.goal.active
            and execution.goal_id == self.goal.id
            and execution.state is GoalExecutionState.STANDBY
            and not (self._throbber is not None and self._throbber.busy)
        )
        status.display = standby
        if standby:
            presentation = execution.presentation("")
            status.update_goal_text(f"{presentation.marker} {presentation.summary}")
