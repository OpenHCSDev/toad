"""A full-height, scrollable projection of a persistent goal."""

from datetime import datetime

from agent_comms.field_codec import FieldCodec
from agent_comms.goals import Goal
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from toad.widgets.comms_sidebar import SelectTarget
from toad.goal_interaction import GoalSession
from toad.widgets.goal_text import GoalText


class GoalDetails(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close")]
    AUTO_FOCUS = "#goal-document"
    DEFAULT_CSS = """
    GoalDetails { align: center middle; background: $background 40%; }
    GoalDetails > Vertical {
        width: 95%; height: 95%; padding: 1;
        border: solid $primary; background: $surface;
    }
    GoalDetails #goal-document { height: 1fr; scrollbar-gutter: stable; }
    GoalDetails .goal-text { height: auto; margin-bottom: 1; }
    GoalDetails Button { dock: bottom; margin-top: 1; }
    """

    def __init__(self, source: GoalSession, *, history=()):
        super().__init__()
        self.source = source
        self.history = history

    @property
    def goal_display(self):
        return self.source.display

    @property
    def execution(self):
        return self.source.execution

    def compose(self) -> ComposeResult:
        with Vertical():
            with VerticalScroll(id="goal-document"):
                yield Static("", markup=False, id="goal-current-heading")
                yield GoalText(classes="goal-text", id="goal-current-objective")
                yield GoalText(classes="goal-text", id="goal-current-progress")
                if self.history:
                    yield Static("Revision history", markup=False)
                    for entry in reversed(self.history):
                        goal_data = entry["after"] or entry["before"]
                        revision_goal = FieldCodec.decode(Goal, goal_data)
                        when = (
                            datetime.fromtimestamp(entry["observed_at"])
                            .astimezone()
                            .strftime("%Y-%m-%d %H:%M:%S")
                        )
                        kind = entry["kind"].replace("_", " ")
                        yield Static(
                            f"Revision {revision_goal.revision} · {kind} · observed {when}",
                            markup=False,
                        )
                        yield GoalText(revision_goal.summary, classes="goal-text")
                        if revision_goal.progress:
                            yield GoalText(revision_goal.progress, classes="goal-text")
            yield Button("Close (Esc)", id="goal-details-close")

    def on_mount(self) -> None:
        self.watch(self.source.view, "goal_display", self._update_current)
        self.watch(self.source.view, "goal_execution", self._update_current)

    def _update_current(self) -> None:
        if not self.is_attached:
            return
        widget = self.query_one_optional("#goal-current-heading", Static)
        if widget is None:
            return
        goal = self.goal_display.snapshot
        heading = self.goal_display.details_heading(self.execution)
        widget.update(heading)
        self.query_one("#goal-current-objective", GoalText).update_goal_text(
            f"Objective: {goal.text}" if goal else ""
        )
        self.query_one("#goal-current-progress", GoalText).update_goal_text(
            f"Progress: {goal.progress}" if goal and goal.progress else ""
        )

    @on(Button.Pressed, "#goal-details-close")
    def action_close(self) -> None:
        self.dismiss(None)

    @on(SelectTarget)
    def open_target(self, event: SelectTarget) -> None:
        event.stop()
        self.dismiss(None)
        self.app.post_message(SelectTarget(event.target))
