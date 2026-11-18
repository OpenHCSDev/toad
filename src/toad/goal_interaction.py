"""Goal controls, dialogs and writes stay bound to their source."""
from __future__ import annotations

from weakref import ReferenceType, ref

from agent_comms.errors import GoalRefused
from agent_comms.planning.goal_presentation import GoalExecutionControls
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

    def unavailable(self) -> None:
        self.view.feedback.flash(self.display.heading(self.execution))

    def after_change(self, binding: GoalSource) -> None:
        self.view.prompt.focus()

    def show_history(self, binding: GoalSource, page: GoalHistoryPage) -> None:
        self.present(GoalDetails(self.view, history=page.history))

    async def open_edit(self) -> None:
        """Open the goal's editor over its owner's mention candidates."""
        view = self.view
        goal = view.goal_display.snapshot.require()
        source = view.goal_source

        async def save(text: str) -> None:
            if not self.owns(source):
                raise GoalRefused("The goal presentation changed; reopen its editor.")
            await self.write(source, source.edit_goal(goal, text))

        observed = await view.app.preparation.run_thread(view.app.coordination_access.observation.observed)
        self.present(GoalEdit(
            goal, goal_mention_candidates(observed), project=view.project_path, on_save=save))

    def toggle_collapsed(self) -> None:
        bar = self.view.goal_bar
        bar.collapsed = not bar.collapsed

    def close(self) -> None:
        modal = self.modal
        if modal is not None and modal.is_attached:
            modal.dismiss()
        self._modal = None
