"""Toolkit-neutral goal controls: the goal bar's buttons, its state, and the session they act on.

Both the Textual goal bar and the Qt goal bar inherit these. The buttons are the one
GoalInteraction family, drawn through the neutral GoalInteractionControl contract; every button acts on a
GoalControlsSession the frontend provides, which owns how a press is activated, how a write
settles and how a refusal is reported. GoalBarOwner decides what the bar shows for a goal,
its execution and the collapse; the frontends only draw it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from agent_comms.coordination.errors import Refused
from agent_comms.errors import GoalRefused
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import GoalId
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.planning.goal_history import RecordedGoalHistory
from agent_comms.planning.goal_presentation import GoalExecutionControls, GoalSnapshot
from agent_comms.planning.goals import Goal, GoalDeclaration
from agent_comms.ui_model.goal import GoalDisplay
from metaclass_registry import AbstractHooksMeta

from toad.client.host import CommsHost


class GoalSource(ABC):
    """Where a goal view reads and changes its owner's goal: a live session's agent connection,
    or a thread's comms goal source (every Qt view, and a TUI view with no agent, such as a
    CLI's mailbox). GoalObservation reads through it and GoalControlsSession writes through it,
    so both frontends observe and change the goal by the one procedure."""

    @abstractmethod
    async def get_goal_snapshot(self) -> GoalSnapshot:
        """The owner's current goal and execution."""

    @abstractmethod
    async def update_goal(self, action: type[GoalAction], text: str = "") -> GoalDeclaration:
        """Set (with `text`), pause, resume, retry or clear the goal."""

    @abstractmethod
    async def edit_goal(self, goal: Goal, text: str) -> Goal:
        """Edit the goal's text, keeping its identity."""

    @abstractmethod
    async def get_goal_history(self, goal_id: GoalId) -> RecordedGoalHistory:
        """The goal's recorded revisions and failed attempts."""

    def presentation_changed(self, observation) -> None:
        """The goal's thread presentation changed. A source whose owner announces its goal
        changes (a live agent) has nothing to do; one that reads Core asks for a fresh read."""

    @abstractmethod
    def matches_agent(self, agent) -> bool:
        """Whether `agent` is this source."""

    @abstractmethod
    def invalidate_observation(self, observation) -> None:
        """Ask `observation` to read this source again."""


class GoalControlsSession[Binding: GoalSource](metaclass=AbstractHooksMeta):
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

    async def change(self, action: type[GoalAction], text: str = "") -> None:
        """Apply a goal action (pause, resume, clear, …) and settle by reading the owner.
        Ownership is rechecked around the write; the backend-specific binding call is the
        one hook, so Textual and Qt sessions do not restate this envelope."""
        binding = self.binding
        if not self.owns(binding):
            return
        goal = self.display.snapshot.require()
        with self.reporting_refusals(binding):
            await self.write(binding, self.apply_goal_change(binding, action, goal, text))
        if self.owns(binding):
            self.after_change(binding)

    def apply_goal_change(
        self, binding: Binding, action: type[GoalAction], goal: Goal, text: str
    ) -> Awaitable[Any]:
        """The write the base `change()` envelope awaits, through the session's goal source.
        Goal state governs continuation, never interruption of an active turn."""
        return binding.update_goal(action, text)

    def after_change(self, binding: Binding) -> None:
        """Hook run after a successful change while the session still owns the binding.
        Textual focuses the composer; Qt has no default follow-up."""

    def unavailable(self) -> None:
        """Report that an action is not available now, without changing the goal."""
        self.report_unavailable(self.display.heading(self.execution))

    @abstractmethod
    def report_unavailable(self, heading: str) -> None:
        """Show the unavailable heading in the frontend's own way."""

    async def open_history(self) -> None:
        """Read the owner's goal history and show it the frontend's own way. The read and
        the ownership recheck are the shared envelope; each frontend only draws the page."""
        binding = self.binding
        goal = self.display.snapshot.require()
        history = await self.read_goal_history(binding, goal)
        if self.owns(binding):
            self.show_history(binding, GoalHistoryPage(history))

    async def read_goal_history(self, binding: Binding, goal: Goal) -> RecordedGoalHistory:
        """Read the goal's revisions and failed attempts through the binding."""
        return await binding.get_goal_history(goal.id)

    def show_history(self, binding: Binding, page: GoalHistoryPage) -> None:
        """Present the history page in the frontend's own view."""
        self.present(self.history_view(page))

    @abstractmethod
    def present(self, view: Any) -> None:
        """Present a goal dialog or modal and track it so `close()` can dismiss it."""

    @abstractmethod
    def history_view(self, page: GoalHistoryPage) -> Any:
        """Build the frontend's history view for `page`."""

    async def open_edit(self) -> None:
        """Open the goal's editor bound to the current goal and source."""
        goal = self.display.snapshot.require()
        source = self.binding

        async def save(text: str) -> None:
            if not self.owns(source):
                raise GoalRefused("The goal presentation changed; reopen its editor.")
            await self.write(source, source.edit_goal(goal, text))

        view = await self.edit_view(goal, save)
        if self.owns(source):
            self.present(view)

    @abstractmethod
    async def edit_view(self, goal: Goal, on_save: Callable[[str], Awaitable[None]]) -> Any:
        """Build the frontend's goal editor calling `on_save` on submit."""

    def close(self) -> None:
        """Dismiss whatever history or edit view this session opened. Default is no-op; the
        frontend subclass overrides when its dialogs are addressable from here."""

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


class GoalCollapse:
    """The goal document owns whether its controls are collapsed."""

    collapsed: bool


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
