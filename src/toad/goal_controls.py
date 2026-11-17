"""Toolkit-neutral goal controls: the goal bar's buttons, its state, and the session they act on.

Both the Textual goal bar and the Qt goal bar inherit these. The buttons are the one
GoalInteraction family, drawn through the neutral GoalInteractionControl contract; every button acts on a
GoalControlsSession the frontend provides, which owns how a press is activated, how a write
settles and how a refusal is reported. GoalBarOwner decides what the bar shows for a goal,
its execution and the collapse; the frontends only draw it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from agent_comms.coordination.errors import Refused
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.planning.goal_history import RecordedGoalHistory
from agent_comms.planning.goal_presentation import GoalExecutionControls, GoalSnapshot
from agent_comms.ui_model.goal import GoalDisplay
from metaclass_registry import AbstractHooksMeta

from toad.client.host import CommsHost


class GoalSource(ABC):
    """Where a goal view reads its owner's goal: a session's agent connection in the TUI, a
    thread's comms goal source on the phone. GoalObservation reads, publishes or degrades
    through it, so both frontends observe the goal by the one procedure."""

    @abstractmethod
    async def get_goal_snapshot(self) -> GoalSnapshot:
        """The owner's current goal and execution."""

    @abstractmethod
    def matches_agent(self, agent) -> bool:
        """Whether `agent` is this source."""

    @abstractmethod
    def invalidate_observation(self, observation) -> None:
        """Ask `observation` to read this source again."""


class GoalControlsSession[Binding](metaclass=AbstractHooksMeta):
    """What a goal button acts on, without a toolkit. The Textual GoalSession binds to its
    agent connection, the Qt one to the thread's comms goal source; each press runs against
    the binding it started with and stops as soon as the session no longer owns it."""

    @property
    @abstractmethod
    def display(self) -> GoalDisplay:
        """The current goal: whether it exists, whether it can be controlled, its snapshot."""

    @property
    @abstractmethod
    def execution(self) -> GoalExecutionControls:
        """The goal's execution: its status label, whether it can pause or resume."""

    @property
    @abstractmethod
    def host(self) -> CommsHost:
        """Where a refused action is reported."""

    @property
    @abstractmethod
    def binding(self) -> Binding:
        """The source this session reads and writes the goal through now."""

    @abstractmethod
    def owns(self, binding: Binding) -> bool:
        """Whether this session still shows the goal of `binding`."""

    @abstractmethod
    async def refresh(self, binding: Binding) -> None:
        """Read the owner's goal again and show it."""

    @abstractmethod
    async def change(self, action: type[GoalAction], text: str = "") -> None:
        """Apply a goal action (pause, resume, clear, …) and settle by reading the owner."""

    @abstractmethod
    def unavailable(self) -> None:
        """Report that an action is not available now, without changing the goal."""

    @abstractmethod
    async def open_history(self) -> None:
        """Show the goal's revision history, the frontend's own way."""

    @abstractmethod
    async def open_edit(self) -> None:
        """Open the goal's editor, the frontend's own way."""

    @abstractmethod
    def toggle_collapsed(self) -> None:
        """Expand or collapse the goal document."""

    async def activate(self, action: type[GoalInteraction]) -> None:
        """One press: read the owner first, then apply the button if it is still enabled."""
        binding = self.binding
        if not self.owns(binding):
            return
        await self.refresh(binding)
        if not self.owns(binding):
            return
        if not action.enabled(self):
            self.unavailable()
            return
        with self.reporting_refusals(binding):
            await action.apply(self)

    @contextmanager
    def reporting_refusals(self, binding: Binding) -> Iterator[None]:
        """Buttons and slash controls report once, only to their original source."""
        try:
            yield
        except Refused as error:
            if not self.owns(binding):
                raise
            self.host.show_error(error, "Goal action failed")

    async def write[Result](self, binding: Binding, operation: Awaitable[Result]) -> Result:
        """Every write settles by reading the owner, including rejected writes."""
        try:
            return await operation
        finally:
            if self.owns(binding):
                await self.refresh(binding)


class GoalInteraction(
    DeclaredFamily, affix="Interaction", discovery_package="toad.goal_interactions",
):
    """One goal button. Its label, whether it is enabled or shown and what it does read only
    from the session, so the Textual and Qt bars offer the same buttons in the same states."""

    label: ClassVar[str]

    @classmethod
    def enabled(cls, session: GoalControlsSession) -> bool:
        return session.display.can_control

    @classmethod
    def visible(cls, session: GoalControlsSession) -> bool:
        return True

    @classmethod
    def caption(cls, session: GoalControlsSession, collapsed: bool) -> str:
        return cls.label

    @classmethod
    @abstractmethod
    async def apply(cls, session: GoalControlsSession) -> None: ...


class GoalInteractionControl(metaclass=AbstractHooksMeta):
    """One goal button as a frontend draws it — a Textual Static, a Qt button. The goal bar
    presents every button through these calls; it holds the interaction it stands for."""

    interaction: type[GoalInteraction]

    @abstractmethod
    def set_shown(self, shown: bool) -> None:
        """Show or hide the button."""

    @abstractmethod
    def set_label(self, label: str) -> None:
        """The button's text."""

    @abstractmethod
    def set_enabled(self, enabled: bool) -> None:
        """Whether the button can be pressed."""


class GoalBarOwner(metaclass=AbstractHooksMeta):
    """The goal bar: one button per GoalInteraction, the state line, the goal's document and
    the standby row. Both frontends inherit it, build `actions` from `goal_interactions()`, and
    draw what `present_goal_document` and `present_goal_state` decide through the hooks."""

    actions: tuple[GoalInteractionControl, ...]

    @staticmethod
    def goal_interactions() -> Iterable[type[GoalInteraction]]:
        return GoalInteraction.members_with(GoalInteraction)

    def present_goal_document(self, display: GoalDisplay) -> None:
        """The goal's own text; an execution or collapse change never re-reads it."""
        goal = display.snapshot
        self.show_goal(display.visible)
        self.show_goal_text(f"Objective: {goal.objective}", f"Progress: {goal.progress}", goal.shows_progress)

    def present_goal_state(self, session: GoalControlsSession, collapsed: bool) -> None:
        """What depends on the goal, its execution and the collapse together."""
        display, execution = session.display, session.execution
        self.show_heading(display.heading(execution))
        for control in self.actions:
            interaction = control.interaction
            control.set_enabled(interaction.enabled(session))
            control.set_shown(interaction.visible(session))
            control.set_label(interaction.caption(session, collapsed))
        self.show_document(display.snapshot.shows_document and not collapsed)
        standby = display.standby(execution)
        self.show_standby(standby and not collapsed)
        if standby:
            self.show_execution_text(execution.presentation("").summary)

    @abstractmethod
    def show_goal(self, visible: bool) -> None:
        """Show the bar while there is a goal to show."""

    @abstractmethod
    def show_goal_text(self, objective: str, progress: str, shows_progress: bool) -> None:
        """The document's objective and progress lines."""

    @abstractmethod
    def show_heading(self, heading: str) -> None:
        """The state line: ``Goal · <status> · rev <n>``, or ``No current goal``."""

    @abstractmethod
    def show_document(self, shown: bool) -> None:
        """Show the goal's document; a collapsed bar hides it."""

    @abstractmethod
    def show_standby(self, shown: bool) -> None:
        """The standby row and its pulse."""

    @abstractmethod
    def show_execution_text(self, text: str) -> None:
        """What the standing-by goal is waiting for."""


@dataclass(frozen=True)
class GoalRevisionEntry:
    """One revision in a goal's history, as both frontends' history views list it."""

    heading: str
    texts: tuple[str, ...]


@dataclass(frozen=True)
class GoalHistoryPage:
    """A goal's recorded history as the history view reads it: revisions newest first, then
    the failed attempts."""

    history: RecordedGoalHistory

    def revisions(self) -> Iterator[GoalRevisionEntry]:
        for entry in reversed(self.history.history):
            goal = (entry.after if entry.after.shows_document else entry.before).require()
            when = datetime.fromtimestamp(entry.observed_at).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            kind = entry.kind.declared_name.replace("_", " ")
            yield GoalRevisionEntry(
                f"Revision {goal.revision} · {kind} · observed {when}",
                (goal.summary, goal.progress) if goal.progress else (goal.summary,))

    def failures(self) -> Iterator[str]:
        for evidence in reversed(self.history.failures):
            failure = evidence.failure.declared_name.replace("_", " ")
            yield f"Attempt {evidence.generation} · revision {evidence.goal_revision} · {failure}"
