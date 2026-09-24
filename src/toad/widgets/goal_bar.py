"""Visible controls for the server-owned persistent thread goal."""

from textual import events
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup
from textual.message import Message
from textual.reactive import var
from textual.widgets import Static
from agent_comms import Goal


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
        controls = self._prompt.query_one_optional(".delivery-controls") if self._prompt else None
        loading = throbber is not None and throbber.busy and throbber.display and throbber.visible
        queue_visible = controls is not None and controls.display and controls.visible
        # Reuse the theme-resolved separator; only these local box edges change.
        self.styles.border_top = ("none", "transparent") if loading else None
        self.styles.border_bottom = self.styles.base.border_top if queue_visible else None

    def compose(self) -> ComposeResult:
        yield Static(markup=False, classes="goal-summary")
        yield Static(markup=False, classes="goal-progress")
        with HorizontalGroup():
            yield GoalControl("Expand", id="goal-expand")
            yield GoalControl("Pause", id="goal-toggle")
            yield GoalControl("Edit", id="goal-edit")
            yield GoalControl("Clear", id="goal-clear")

    def watch_goal(self, goal: Goal | None):
        self.display = goal is not None
        if goal is not None:
            self.query_one(".goal-summary", Static).update(
                goal.summary
            )
            progress = self.query_one(".goal-progress", Static)
            progress.update(goal.progress)
            progress.display = bool(goal.progress)
            toggle = self.query_one("#goal-toggle", Static)
            toggle.update(goal.toggle_label)
            toggle.display = goal.status != "completed"
