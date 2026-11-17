"""Goal controls, dialogs and writes stay bound to their source."""
from __future__ import annotations

from collections.abc import Awaitable
from typing import Any
from weakref import ReferenceType, ref

from agent_comms.errors import GoalRefused
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.planning.goal_history import RecordedGoalHistory
from agent_comms.planning.goal_presentation import GoalExecutionControls
from agent_comms.planning.goals import Goal
from toad.agent_binding import AgentConnection
from toad.goal_controls import GoalControlsSession, GoalHistoryPage

from toad.screens.goal_details import GoalDetails
from toad.screens.goal_edit import GoalEdit
from toad.screens.modal import ModalScreen
from toad.goal_view import GoalView
from toad.widgets.goal_text import goal_mention_candidates


class GoalSession(GoalControlsSession[AgentConnection]):
    """The Textual goal controls: the optional modal and the writes for this source binding.
    It is the GoalControlsSession the GoalInteraction family acts on; the base owns the
    `change`/`open_history` envelopes, so only the backend-specific hooks live here."""

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

    def owns(self, agent: AgentConnection) -> bool:
        view = self.view
        if not view.is_attached:
            return False
        return view.goal_controls is self and view.agent_binding is agent

    def present(self, modal: ModalScreen[None]) -> None:
        self._modal = ref(modal)
        self.view.app.push_screen(modal)

    @property
    def host(self):
        return self.view.app

    @property
    def binding(self) -> AgentConnection:
        return self.view.agent_binding

    async def refresh(self, binding: AgentConnection) -> None:
        await self.view.goal_observation.refresh()

    def unavailable(self) -> None:
        self.view.feedback.flash(self.display.heading(self.execution))

    def apply_goal_change(
        self, binding: AgentConnection, action: type[GoalAction], goal: Goal, text: str
    ) -> Awaitable[Any]:
        # Goal state governs continuation, never interruption of an active turn.
        return binding.update_goal(action, text)

    def after_change(self, binding: AgentConnection) -> None:
        self.view.prompt.focus()

    async def read_goal_history(self, binding: AgentConnection, goal: Goal) -> RecordedGoalHistory:
        return await binding.get_goal_history(goal.id)

    def show_history(self, binding: AgentConnection, page: GoalHistoryPage) -> None:
        self.present(GoalDetails(self.view, history=page.history))

    async def open_edit(self) -> None:
        """Open the goal's editor over its owner's mention candidates."""
        view = self.view
        goal = view.goal_display.snapshot.require()
        agent = view.agent_binding

        async def save(text: str) -> None:
            if not self.owns(agent):
                raise GoalRefused("The goal presentation changed; reopen its editor.")
            await self.write(agent, agent.edit_goal(goal, text))

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
