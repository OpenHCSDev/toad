"""Declared goal controls and source-bound modal/write custody."""
from __future__ import annotations

from abc import abstractmethod
from typing import ClassVar, TYPE_CHECKING
from weakref import ref

from agent_comms.declared_family import DeclaredFamily
from agent_comms.goal_actions import ClearGoalAction, GoalAction

if TYPE_CHECKING:
    from toad.goal_display import GoalDisplay
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
        goal, agent = view.goal_display.snapshot, view.agent
        if goal is None:
            return
        history = await agent.get_goal_history(goal.id) if agent is not None else ()
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
        return display.snapshot is not None and not display.snapshot.state.terminal

    @classmethod
    def caption(cls, display, collapsed):
        return display.snapshot.state.toggle_label if display.snapshot else cls.label

    @classmethod
    async def apply(cls, session):
        view = session.view
        action = view.goal_display.snapshot.state.toggle if view.goal_display.snapshot else None
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
        goal, agent = view.goal_display.snapshot, view.agent
        if goal is None or agent is None:
            raise ValueError("Editing requires an agent-comms goal")

        async def save(text: str) -> None:
            if not session.owns(agent):
                raise ValueError("The goal presentation changed; reopen its editor.")
            await session.write(agent, agent.edit_goal(goal, text))

        session.present(GoalEdit(goal, goal_mention_candidates(view.app), on_save=save))


class ClearInteraction(GoalInteraction):
    label = "Clear"

    @classmethod
    async def apply(cls, session):
        await session.change(ClearGoalAction)


class GoalSession:
    """One optional modal and control/poll custody for the actual source binding."""

    def __init__(self, view: Conversation):
        self._view = ref(view)
        self._modal = None

    @property
    def view(self) -> Conversation | None:
        return self._view() if self._view is not None else None

    @property
    def modal(self):
        return self._modal() if self._modal is not None else None

    @property
    def display(self):
        from toad.goal_display import NoGoal
        return self.view.goal_display if self.view is not None else NoGoal()

    @property
    def execution(self):
        return self.view.goal_execution if self.view is not None else None

    def owns(self, agent) -> bool:
        view = self.view
        if view is None or not view.is_attached:
            return False
        return view.goal_controls is self and view.agent is agent

    def present(self, modal) -> None:
        self._modal = ref(modal)
        self.view.app.push_screen(modal)

    async def activate(self, action: type[GoalInteraction]) -> None:
        view = self.view
        if view is None or not self.owns(view.agent):
            return
        agent = view.agent
        try:
            await view.goal_observation.refresh()
            if not self.owns(agent):
                return
            if not action.enabled(view.goal_display):
                view.flash(view.goal_display.heading(view.goal_execution))
                return
            await action.apply(self)
        except (OSError, ValueError) as error:
            if self.owns(agent):
                view.flash(str(error), style="error")

    async def change(self, action: type[GoalAction], text: str = "") -> None:
        view = self.view
        if view is None or not view.is_attached:
            raise ValueError("The goal presentation changed; reopen its controls.")
        agent = view.agent
        if not self.owns(agent):
            raise ValueError("The goal presentation changed; reopen its controls.")
        if agent is None:
            view.flash("Persistent goals require an agent-comms session", style="error")
            return
        try:
            # The existing Agent boundary encodes the declared goal operation.
            # Goal state governs continuation, never interruption of an active turn.
            await self.write(agent, agent.update_goal(action.declared_name, text))
            if self.owns(agent):
                view.prompt.focus()
        except (OSError, ValueError) as error:
            if self.owns(agent):
                view.flash(str(error), style="error")

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

    def poll(self) -> None:
        view = self.view
        if view is None or not view.is_attached:
            return
        try:
            current = view.app.screen
            visible = (current is view.screen and view in view.screen._compositor.visible_widgets
                       or current is self.modal)
        except ScreenStackError, UnknownModeError:
            return
        if visible and not view.goal_observation.active:
            view.goal_observation.invalidate()

    def close(self) -> None:
        self._view = self._modal = None
