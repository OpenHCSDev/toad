"""A full-height, scrollable projection of a persistent goal."""

from agent_comms import Goal
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


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

    def __init__(self, goal: Goal):
        super().__init__()
        self.goal = goal

    def compose(self) -> ComposeResult:
        with Vertical():
            with VerticalScroll(id="goal-document"):
                yield Static(self.goal.summary, markup=False, classes="goal-text")
                if self.goal.progress:
                    yield Static("Progress", markup=False)
                    yield Static(self.goal.progress, markup=False, classes="goal-text")
            yield Button("Close (Esc)", id="goal-details-close")

    @on(Button.Pressed, "#goal-details-close")
    def action_close(self) -> None:
        self.dismiss(None)
