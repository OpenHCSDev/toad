"""A full-height, scrollable projection of a persistent goal."""
from datetime import datetime

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

from toad.goal_interaction import GoalSession
from toad.widgets.goal_text import GoalText
from textual.events import Mount
from textual import on


class GoalDetailsPanel(ModalPanel):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = 1


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

    def __init__(self, source: GoalSession, *, history: RecordedGoalHistory):
        super().__init__()
        self.source = source
        self.history = history.history
        self.failures = history.failures

    @property
    def source_view(self):
        return self.source.view

    @property
    def goal_display(self):
        return self.source.display

    @property
    def execution(self):
        return self.source.execution

    def compose(self) -> ComposeResult:
        with GoalDetailsPanel():
            with GoalDocument():
                yield CurrentHeading("", markup=False)
                yield CurrentObjective()
                yield CurrentProgress()
                if self.history:
                    yield Static("Revision history", markup=False)
                    for entry in reversed(self.history):
                        revision_goal = (entry.after if entry.after.shows_document else entry.before).require()
                        when = (
                            datetime.fromtimestamp(entry.observed_at)
                            .astimezone()
                            .strftime("%Y-%m-%d %H:%M:%S")
                        )
                        kind = entry.kind.declared_name.replace("_", " ")
                        yield Static(
                            f"Revision {revision_goal.revision} · {kind} · observed {when}",
                            markup=False,
                        )
                        yield GoalDetailText(revision_goal.summary)
                        if revision_goal.progress:
                            yield GoalDetailText(revision_goal.progress)
                if self.failures:
                    yield Static("Failed attempts", markup=False)
                    for evidence in reversed(self.failures):
                        failure = evidence.failure.declared_name.replace("_", " ")
                        yield Static(
                            f"Attempt {evidence.generation} · revision {evidence.goal_revision} · {failure}",
                            markup=False,
                        )
            yield GoalDetailsClose("Close")

    @on(Mount)
    def on_mount(self) -> None:
        self.watch(self.source.view, "goal_display", self._update_current)
        self.watch(self.source.view, "goal_execution", self._update_current)

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
