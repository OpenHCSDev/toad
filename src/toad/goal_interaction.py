"""Goal controls, dialogs and writes stay bound to their source."""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from typing import ClassVar
from weakref import ReferenceType, ref

from agent_comms.coordination.errors import Refused
from agent_comms.errors import GoalRefused
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.planning.goal_presentation import GoalExecutionControls
from toad.agent_binding import AgentConnection

from toad.screens.modal import ModalScreen
from toad.goal_view import GoalView


class GoalInteraction(
    DeclaredFamily, affix="Interaction", discovery_package="toad.goal_interactions",
):
    label: ClassVar[str]

    @classmethod
    def enabled(cls, session: GoalSession) -> bool:
        return session.display.can_control

    @classmethod
    def visible(cls, session: GoalSession) -> bool:
        return True

    @classmethod
    def caption(cls, session: GoalSession, collapsed: bool) -> str:
        return cls.label

    @classmethod
    @abstractmethod
    async def apply(cls, session: GoalSession) -> None: ...


class GoalSession:
    """Owns the optional dialog and goal controls for this source binding."""

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

    async def activate(self, action: type[GoalInteraction]) -> None:
        view = self.view
        if not self.owns(view.agent_binding):
            return
        agent = view.agent_binding
        await view.goal_observation.refresh()
        if not self.owns(agent):
            return
        if not action.enabled(self):
            self.unavailable()
            return
        with self.reporting_refusals(agent):
            await action.apply(self)

    def unavailable(self) -> None:
        self.view.feedback.flash(self.display.heading(self.execution))

    @contextmanager
    def reporting_refusals(self, agent: AgentConnection) -> Iterator[None]:
        """Buttons and slash controls report once, only to their original source."""
        try:
            yield
        except Refused as error:
            if not self.owns(agent):
                raise
            self.view.app.show_error(error, "Goal action failed")

    async def change(self, action: type[GoalAction], text: str = "") -> None:
        view = self.view
        agent = view.agent_binding
        if not self.owns(agent):
            raise GoalRefused("The goal presentation changed; reopen its controls.")
        # The existing Agent boundary encodes the declared goal operation.
        # Goal state governs continuation, never interruption of an active turn.
        with self.reporting_refusals(agent):
            await self.write(agent, agent.update_goal(action, text))
            if self.owns(agent):
                view.prompt.focus()

    async def write[Result](self, agent: AgentConnection, operation: Awaitable[Result]) -> Result:
        """Every write settles by reading the owner, including rejected writes."""
        try:
            return await operation
        finally:
            if self.owns(agent):
                await self.view.goal_observation.refresh()

    def close(self) -> None:
        modal = self.modal
        if modal is not None and modal.is_attached:
            modal.dismiss()
        self._modal = None
