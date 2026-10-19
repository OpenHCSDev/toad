"""Goal controls, dialogs and writes stay bound to their source."""
from __future__ import annotations

from abc import abstractmethod
from typing import ClassVar, TYPE_CHECKING
from weakref import ref

from agent_comms.declared_family import DeclaredFamily
from agent_comms.goal_actions import ClearGoalAction, GoalAction
from agent_comms.goal_presentation import ThreadGoalExecution

if TYPE_CHECKING:
    from agent_comms.ui_model.goal import GoalDisplay
    from toad.widgets.conversation import Conversation


class GoalInteraction(DeclaredFamily, affix="Interaction"):
    label: ClassVar[str]

    @classmethod
    def control_id(cls) -> str:
        return f"goal-{cls.declared_name}"

    @classmethod
    def enabled(cls, display: GoalDisplay) -> bool:
        return display.can_control

    @classmethod
    def visible(cls, display: GoalDisplay) -> bool:
        return True

    @classmethod
    def caption(cls, display: GoalDisplay, collapsed: bool) -> str:
        return cls.label

    @classmethod
    @abstractmethod
    async def apply(cls, session: GoalSession) -> None: ...


class HistoryInteraction(GoalInteraction):
    label = "History"

    @classmethod
    async def apply(cls, session):
        from toad.screens.goal_details import GoalDetails
        view = session.view
        goal, agent = view.goal_display.snapshot.require(), view.agent_binding
        history = await agent.get_goal_history(goal.id)
        if not session.owns(agent):
            return
        details = GoalDetails(session, history=history)
        session.present(details)


class CollapseInteraction(GoalInteraction):
    label = "Collapse"

    @classmethod
    def enabled(cls, display):
        return True

    @classmethod
    def caption(cls, display, collapsed):
        return "Expand" if collapsed else cls.label

    @classmethod
    async def apply(cls, session):
        from toad.widgets.goal_bar import GoalBar
        bar = session.view.query_one(GoalBar)
        bar.collapsed = not bar.collapsed


class ToggleInteraction(GoalInteraction):
    label = "Pause"

    @classmethod
    def visible(cls, display):
        return display.can_control and not display.snapshot.require().state.terminal

    @classmethod
    def caption(cls, display, collapsed):
        return display.snapshot.require().state.toggle_label if display.can_control else cls.label

    @classmethod
    async def apply(cls, session):
        view = session.view
        action = view.goal_display.snapshot.require().state.toggle
        if action is None:
            view.flash("This goal is completed; set a new goal to continue.")
        else:
            await session.change(action)


class EditInteraction(GoalInteraction):
    label = "Edit"

    @classmethod
    async def apply(cls, session):
        from toad.screens.goal_edit import GoalEdit
        from toad.widgets.goal_text import goal_mention_candidates
        view = session.view
        goal = view.goal_display.snapshot.require()
        agent = view.agent_binding.goal_editor()

        async def save(text: str) -> None:
            if not session.owns(agent):
                raise ValueError("The goal presentation changed; reopen its editor.")
            await session.write(agent, agent.edit_goal(goal, text))

        observed = await view.app.preparation.run_thread(view.app.coordination_access.observation.observed)
        session.present(GoalEdit(goal, goal_mention_candidates(observed), on_save=save))


class ClearInteraction(GoalInteraction):
    label = "Clear"

    @classmethod
    async def apply(cls, session):
        await session.change(ClearGoalAction)


class GoalSession:
    """Owns the optional dialog and goal controls for this source binding."""

    def __init__(self, view: Conversation):
        self.view = view
        self._modal = None

    @property
    def modal(self):
        return self._modal() if self._modal is not None else None

    @property
    def display(self):
        return self.view.goal_display

    @property
    def execution(self) -> ThreadGoalExecution:
        return self.view.goal_execution

    def owns(self, agent) -> bool:
        view = self.view
        if not view.is_attached:
            return False
        return view.goal_controls is self and view.agent_binding is agent

    def present(self, modal) -> None:
        self._modal = ref(modal)
        self.view.app.push_screen(modal)

    async def activate(self, action: type[GoalInteraction]) -> None:
        view = self.view
        if not self.owns(view.agent_binding):
            return
        agent = view.agent_binding
        await view.goal_observation.refresh()
        if not self.owns(agent):
            return
        if not action.enabled(view.goal_display):
            view.flash(view.goal_display.heading(view.goal_execution))
            return
        await action.apply(self)

    async def change(self, action: type[GoalAction], text: str = "") -> None:
        view = self.view
        if not view.is_attached:
            raise ValueError("The goal presentation changed; reopen its controls.")
        agent = view.agent_binding
        if not self.owns(agent):
            raise ValueError("The goal presentation changed; reopen its controls.")
        # The existing Agent boundary encodes the declared goal operation.
        # Goal state governs continuation, never interruption of an active turn.
        await self.write(agent, agent.update_goal(action, text))
        if self.owns(agent):
            view.prompt.focus()

    async def write(self, agent, operation):
        """Every write settles by reading the owner, including rejected writes."""
        try:
            try:
                return await operation
            finally:
                if self.owns(agent):
                    await self.view.goal_observation.refresh()
        except (OSError, ValueError) as error:
            if self.owns(agent):
                raise ValueError(self.view.goal_display.action_failure(error)) from error
            raise

    def close(self) -> None:
        modal = self.modal
        if modal is not None and modal.is_attached:
            modal.dismiss()
        self._modal = None
