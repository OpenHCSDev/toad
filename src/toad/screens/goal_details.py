"""A full-height goal projection with one bounded newest-first history page."""
from datetime import datetime

from agent_comms.goal_history import (
    Before, GoalHistoryCursor, GoalHistoryQuery, GoalHistoryRevision, Newest, OneGoal,
)
from agent_comms.mro_dispatch import handles
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static
from textual.worker import Worker

from toad.core.input_events import SelectTarget
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from toad.goal_interaction import GoalSession
from toad.project_path_owner import ProjectPathOwner
from toad.screens.modal import ModalScreen
from toad.widgets.goal_text import GoalText


class GoalHistoryRevisionView(Vertical):
    """A rendered immutable revision, also owning its older-page destination."""

    DEFAULT_CSS = "GoalHistoryRevisionView { height: auto; }"

    def __init__(self, revision: GoalHistoryRevision):
        super().__init__()
        self.revision = revision

    @property
    def older(self) -> Before:
        return Before(self.revision.sequence)

    def compose(self) -> ComposeResult:
        goal = self.revision.after or self.revision.before
        when = datetime.fromtimestamp(self.revision.observed_at).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        revision = f"Revision {goal.revision}" if goal is not None else "No goal"
        kind = self.revision.kind.replace("_", " ")
        yield Static(f"{revision} · {kind} · observed {when}", markup=False)
        if goal is not None:
            yield GoalText(goal.summary, classes="goal-text")
            if goal.progress:
                yield GoalText(goal.progress, classes="goal-text")


class GoalDetails(CoreEventReceiver, ProjectPathOwner, ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close")]
    AUTO_FOCUS = "#goal-document"
    DEFAULT_CSS = """
    GoalDetails { align: center middle; background: $background 40%; }
    GoalDetails > Vertical {
        width: 95%; height: 95%; padding: 1;
        border: solid $primary; background: $surface;
    }
    GoalDetails #goal-document { height: 1fr; scrollbar-gutter: stable; }
    GoalDetails #goal-history { height: auto; }
    GoalDetails .goal-text { height: auto; margin-bottom: 1; }
    GoalDetails #goal-history-actions { height: auto; }
    GoalDetails Button { margin-top: 1; margin-right: 1; }
    GoalDetails #goal-details-close { dock: bottom; }
    """

    def __init__(self, source: GoalSession, *, scope: OneGoal):
        super().__init__()
        self.source = source
        self.scope = scope

    @property
    def project_root(self):
        return ProjectPathOwner.containing(self.source.view).project_root

    @property
    def coordination_root(self):
        return ProjectPathOwner.containing(self.source.view).coordination_root

    @property
    def link_context_events(self):
        return ProjectPathOwner.containing(self.source.view).link_context_events

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
                yield Static("Revision history · newest first", markup=False)
                yield Vertical(id="goal-history")
                yield Static("Loading revisions…", markup=False, id="goal-history-status")
            with Horizontal(id="goal-history-actions"):
                yield Button("Newest / refresh", id="goal-history-newest", disabled=True)
                yield Button("Older revisions", id="goal-history-older", disabled=True)
            yield Button("Close (Esc)", id="goal-details-close")

    def on_mount(self) -> None:
        self.watch(self.source.view, "goal_display", self._update_current)
        self.watch(self.source.view, "goal_execution", self._update_current)
        self._read_history(Newest())

    def _read_history(self, cursor: GoalHistoryCursor) -> None:
        self.run_worker(self._load_history(cursor), group="goal-history", exclusive=True)

    @on(Worker.StateChanged)
    def history_loading(self, event: Worker.StateChanged) -> None:
        if event.worker.node is self:
            loading = any(worker.node is self and not worker.is_finished for worker in self.workers)
            self.query_one("#goal-history-newest", Button).disabled = loading
            self.query_one("#goal-history-older", Button).disabled = loading

    async def _load_history(self, cursor: GoalHistoryCursor) -> None:
        view = self.source.view
        if view is None or not self.source.owns(view.agent) or view.agent is None:
            self.query_one("#goal-history-status", Static).update("No active goal-history connection.")
            return
        agent = view.agent
        older = self.query_one("#goal-history-older", Button)
        status = self.query_one("#goal-history-status", Static)
        status.update("Loading revisions…")
        try:
            page = await agent.get_goal_history(GoalHistoryQuery(scope=self.scope, cursor=cursor))
            if not self.is_attached or not self.source.owns(agent):
                return
            if page:
                history = self.query_one("#goal-history", Vertical)
                await history.remove_children()
                await history.mount(*(GoalHistoryRevisionView(entry) for entry in page))
                self.query_one("#goal-document", VerticalScroll).scroll_home(animate=False)
                status.update(f"Showing {len(page)} revisions · newest first")
            else:
                status.update("No older revisions available.")
            older.display = len(page) == GoalHistoryQuery.MAX_ROWS
        except (OSError, ValueError) as error:
            if self.is_attached and self.source.owns(agent):
                status.update(str(error))

    @on(Button.Pressed, "#goal-history-newest")
    def newest_history(self) -> None:
        self._read_history(Newest())

    @on(Button.Pressed, "#goal-history-older")
    def older_history(self) -> None:
        rows = self.query(GoalHistoryRevisionView)
        if rows:
            self._read_history(rows.last().older)

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

    @handles(SelectTarget)
    def open_target(self, event: CoreEventMessage) -> None:
        event.stop()
        self.dismiss(None)
        if (view := self.source.view) is not None:
            view.publish_core(event.event)
