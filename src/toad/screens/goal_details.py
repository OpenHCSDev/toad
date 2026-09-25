"""A full-height, scrollable projection of a persistent goal."""

from datetime import datetime

from agent_comms import Goal
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from toad.widgets.comms_sidebar import SelectTarget
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

    def __init__(self, goal: Goal, *, history=()):
        super().__init__()
        self.goal = goal
        self.history = history

    def compose(self) -> ComposeResult:
        with Vertical():
            with VerticalScroll(id="goal-document"):
                yield GoalText(self.goal.summary, classes="goal-text")
                if self.goal.progress:
                    yield Static("Progress", markup=False)
                    yield GoalText(self.goal.progress, classes="goal-text")
                if self.history:
                    yield Static("Revision history", markup=False)
                    for entry in reversed(self.history):
                        goal_data = entry["after"] or entry["before"]
                        revision_goal = Goal(**goal_data)
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

    @on(Button.Pressed, "#goal-details-close")
    def action_close(self) -> None:
        self.dismiss(None)

    @on(SelectTarget)
    def open_target(self, event: SelectTarget) -> None:
        event.stop()
        self.dismiss(None)
        self.app.post_message(SelectTarget(event.target, event.kind))
