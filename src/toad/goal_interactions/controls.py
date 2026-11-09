"""Original goal interaction members with normal dialog dependencies."""

from __future__ import annotations

from agent_comms.errors import GoalRefused
from agent_comms.planning.goal_actions import ClearGoalAction
from agent_comms.planning.goal_history import RecordedGoalHistory
from agent_comms.planning.goal_presentation import GoalExecutionControls
from toad.screens.goal_details import GoalDetails
from toad.screens.goal_edit import GoalEdit
from toad.widgets.goal_text import goal_mention_candidates

from toad.goal_interaction import GoalInteraction
from toad.goal_interaction import GoalSession


class HistoryInteraction(GoalInteraction):
    label = "History"

    @classmethod
    async def apply(cls, session: GoalSession) -> None:
        view = session.view
        goal, agent = view.goal_display.snapshot.require(), view.agent_binding
        history: RecordedGoalHistory = await agent.get_goal_history(goal.id)
        if not session.owns(agent):
            return
        details = GoalDetails(session, history=history)
        session.present(details)


class CollapseInteraction(GoalInteraction):
    label = "Collapse"

    @classmethod
    def enabled(cls, session):
        return True

    @classmethod
    def caption(cls, session, collapsed):
        return "Expand" if collapsed else cls.label

    @classmethod
    async def apply(cls, session):
        bar = session.view.goal_bar
        bar.collapsed = not bar.collapsed


class ToggleInteraction(GoalInteraction):
    label = GoalExecutionControls.toggle_label

    @classmethod
    def visible(cls, session: GoalSession) -> bool:
        return super().enabled(session) and session.execution.can_toggle()

    @classmethod
    def caption(cls, session: GoalSession, collapsed: bool) -> str:
        return session.execution.toggle_label if cls.visible(session) else cls.label

    @classmethod
    async def apply(cls, session: GoalSession) -> None:
        await session.execution.apply_toggle(session.change, session.unavailable)


class EditInteraction(GoalInteraction):
    label = "Edit"

    @classmethod
    async def apply(cls, session: GoalSession) -> None:
        view = session.view
        goal = view.goal_display.snapshot.require()
        agent = view.agent_binding

        async def save(text: str) -> None:
            if not session.owns(agent):
                raise GoalRefused("The goal presentation changed; reopen its editor.")
            await session.write(agent, agent.edit_goal(goal, text))

        observed = await view.app.preparation.run_thread(view.app.coordination_access.observation.observed)
        session.present(GoalEdit(
            goal, goal_mention_candidates(observed), project=view.project_path, on_save=save))


class ClearInteraction(GoalInteraction):
    label = "Clear"

    @classmethod
    async def apply(cls, session):
        await session.change(ClearGoalAction)
