"""A full-height, scrollable projection of a persistent goal."""

from agent_comms.planning.goal_history import RecordedGoalHistory
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from toad.widgets.acting_button import DismissButton
from toad.native_style import (
    AutoHeight,
    DockedBottom,
    SpacedAbove,
    SpacedBelow,
    StableGutter,
)
from toad.screens.modal import CenteredScreen, ModalPanel, ShadedScreen
from toad.screens.source_modal import SourceModal

from textual.widgets import Static

from toad.goal_controls import GoalHistoryPage
from toad.goal_view import GoalView
from toad.widgets.goal_text import GoalText
from textual.events import Mount
from textual import on


class OneCellPadding:
    """Widget padded by one cell on every side."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = 1


class GoalDetailsPanel(OneCellPadding, ModalPanel):
    pass


class GoalDocument(StableGutter, VerticalScroll):
    """Its look is its bases."""


class GoalDetailText(SpacedBelow, GoalText, AutoHeight):
    """Its look is its bases."""


class CurrentHeading(Static):
    """The current goal's state line."""


class CurrentObjective(GoalDetailText):
    """The current goal's objective."""


class CurrentProgress(GoalDetailText):
    """The current goal's progress."""


class GoalDetailsClose(SpacedAbove, DockedBottom, DismissButton):
    """Its look is its bases."""


class GoalDetails(ShadedScreen, CenteredScreen, SourceModal):
    AUTO_FOCUS = "GoalDocument"

    def __init__(self, view: GoalView, *, history: RecordedGoalHistory):
        super().__init__()
        self.view = view
        self.history = GoalHistoryPage(history)

    @property
    def source_view(self):
        return self.view

    @property
    def goal_display(self):
        return self.view.goal_display

    @property
    def execution(self):
        return self.view.goal_execution

    def compose(self) -> ComposeResult:
        with GoalDetailsPanel():
            with GoalDocument():
                yield CurrentHeading("", markup=False)
                yield CurrentObjective()
                yield CurrentProgress()
                revisions = tuple(self.history.revisions())
                if revisions:
                    yield Static("Revision history", markup=False)
                    for revision in revisions:
                        yield Static(revision.heading, markup=False)
                        for text in revision.texts:
                            yield GoalDetailText(text)
                failures = tuple(self.history.failures())
                if failures:
                    yield Static("Failed attempts", markup=False)
                    for failure in failures:
                        yield Static(failure, markup=False)
            yield GoalDetailsClose("Close")

    @on(Mount)
    def on_mount(self) -> None:
        self.watch(self.view, "goal_display", self._update_current)
        self.watch(self.view, "goal_execution", self._update_current)

    def _update_current(self) -> None:
        if not self.is_attached:
            return
        widget = self.query_one_optional(CurrentHeading)
        if widget is None:
            return
        state = self.goal_display
        goal = state.snapshot
        heading = state.details_heading(self.execution)
        widget.update(heading)
        objective = self.query_one(CurrentObjective)
        objective.update_goal_text(f"Objective: {goal.objective}")
        objective.display = goal.shows_document
        progress = self.query_one(CurrentProgress)
        progress.update_goal_text(f"Progress: {goal.progress}")
        progress.display = goal.shows_progress
