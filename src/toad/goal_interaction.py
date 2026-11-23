"""Goal controls, dialogs and writes stay bound to their source."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from weakref import ReferenceType, ref

from agent_comms.planning.goal_presentation import GoalExecutionControls
from agent_comms.planning.goals import Goal
from toad.goal_controls import GoalControlsSession, GoalHistoryPage, GoalSource

from toad.screens.goal_details import GoalDetails
from toad.screens.goal_edit import GoalEdit
from toad.screens.modal import ModalScreen
from toad.goal_view import GoalView
from toad.widgets.goal_text import goal_mention_candidates


class GoalSession(GoalControlsSession[GoalSource]):
    """The Textual goal controls: the optional modal for this view's goal source. It is the
    GoalControlsSession the GoalInteraction family acts on; the base owns the writes and the
    `change`/`open_history` envelopes, so only the Textual presentation lives here."""

    def __init__(self, view: GoalView[GoalSession]):
        self.view = view
        self._modal: ReferenceType[ModalScreen[None]] | None = None

    @property
    def modal(self) -> ModalScreen[None] | None:
        return self._modal() if self._modal is not None else None

    @property
    def display(self):
        return self.view.goal_display

    @property
    def execution(self) -> GoalExecutionControls:
        return self.view.goal_execution

    def owns(self, source: GoalSource) -> bool:
        view = self.view
        if not view.is_attached:
            return False
        return view.goal_controls is self and view.goal_source is source

    def present(self, modal: ModalScreen[None]) -> None:
        self._modal = ref(modal)
        self.view.app.push_screen(modal)

    @property
    def host(self):
        return self.view.app

    @property
    def binding(self) -> GoalSource:
        return self.view.goal_source

    async def refresh(self, binding: GoalSource) -> None:
        await self.view.goal_observation.refresh()

    def report_unavailable(self, heading: str) -> None:
        self.view.feedback.flash(heading)

    def after_change(self, binding: GoalSource) -> None:
        self.view.prompt.focus()

    def history_view(self, page: GoalHistoryPage) -> GoalDetails:
        return GoalDetails(self.view, history=page.history)

    async def edit_view(self, goal: Goal, on_save: Callable[[str], Awaitable[None]]) -> GoalEdit:
        """Build the goal's editor over its owner's mention candidates."""
        view = self.view
        observed = await view.app.preparation.run_thread(view.app.coordination_access.observation.observed)
        return GoalEdit(goal, goal_mention_candidates(observed), project=view.project_path, on_save=on_save)

    def toggle_collapsed(self) -> None:
        bar = self.view.goal_bar
        bar.collapsed = not bar.collapsed

    def close(self) -> None:
        modal = self.modal
        if modal is not None and modal.is_attached:
            modal.dismiss()
        self._modal = None
