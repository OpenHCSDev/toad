"""The goal buttons: History, Expand/Collapse, Pause/Resume, Edit and Clear.

Each acts only through the GoalControlsSession, so the Textual and Qt goal bars run the same
buttons. The session owns how History and Edit are shown and how the document collapses.
"""

from __future__ import annotations

from agent_comms.planning.goal_actions import ClearGoalAction
from agent_comms.planning.goal_presentation import GoalExecutionControls

from toad.goal_controls import GoalControlsSession, GoalInteraction


class HistoryInteraction(GoalInteraction):
    label = "History"

    @classmethod
    async def apply(cls, session: GoalControlsSession) -> None:
        await session.open_history()


class CollapseInteraction(GoalInteraction):
    label = "Collapse"

    @classmethod
    def enabled(cls, session: GoalControlsSession) -> bool:
        return True

    @classmethod
    def caption(cls, session: GoalControlsSession, collapsed: bool) -> str:
        return "Expand" if collapsed else cls.label

    @classmethod
    async def apply(cls, session: GoalControlsSession) -> None:
        session.toggle_collapsed()


class ToggleInteraction(GoalInteraction):
    label = GoalExecutionControls.toggle_label

    @classmethod
    def visible(cls, session: GoalControlsSession) -> bool:
        return super().enabled(session) and session.execution.can_toggle()

    @classmethod
    def caption(cls, session: GoalControlsSession, collapsed: bool) -> str:
        return session.execution.toggle_label if cls.visible(session) else cls.label

    @classmethod
    async def apply(cls, session: GoalControlsSession) -> None:
        await session.execution.apply_toggle(session.change, session.unavailable)


class EditInteraction(GoalInteraction):
    label = "Edit"

    @classmethod
    async def apply(cls, session: GoalControlsSession) -> None:
        await session.open_edit()


class ClearInteraction(GoalInteraction):
    label = "Clear"

    @classmethod
    async def apply(cls, session: GoalControlsSession) -> None:
        await session.change(ClearGoalAction)
