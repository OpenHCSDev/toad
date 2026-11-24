"""The agent itself is a bound connection; a saved view may be unbound."""

from __future__ import annotations

from abc import abstractmethod
from functools import cached_property
from pathlib import Path
from typing import ClassVar, TYPE_CHECKING

from agent_comms.registry.thread_presentation import ThreadPresentation
from agent_comms.errors import GoalRefused
from agent_comms.planning.goal_history import RecordedGoalHistory
from agent_comms.planning.goal_presentation import GoalSnapshot, IdleGoalExecution
from agent_comms.planning.goals import NoGoal

from toad.acp.agent_configuration import AgentConfiguration
from toad.acp.agent_session import SessionDisposition, UnopenedSessionDisposition
from toad.goal_controls import GoalSource
from toad.agent_presentation import AgentPresentation, LocalAgentPresentation
from toad.core.events import CoreEventStream
from toad.client.input_decision import InputAccepted, InputDecision, NoLiveAgent
from toad.commit_claims import CommitSource
from toad.conversation_turn import TurnOwner
from toad.core.events import Publication
from toad.acp.comms_updates import ThreadRead
from agent_comms.nominal.field_codec import AcpSessionId

if TYPE_CHECKING:
    from agent_comms.planning.goal_actions import GoalAction
    from agent_comms.planning.goals import (
    Goal,
    GoalDeclaration,
)
    from agent_comms.nominal.field_codec import GoalId
    from agent_comms.registry.thread_presentation import ExistingSessionLoadPlan
    from toad.acp.agent_controller import AgentController

    from toad.client.submission import SubmissionStart
    from toad.conversation_submission import (
        AgentInputSubmission,
        ConversationSubmissions,
    )
    from toad.screens.main import MainScreen
    from toad.session_observation import SessionObservation
    from toad.session_presentation import OperationalSessionSources
    from toad.widgets.conversation import Conversation, ConversationSessionBinding


class AgentConnection(GoalSource):
    events: CoreEventStream
    configuration: AgentConfiguration
    presentation: AgentPresentation
    ready: bool
    session_disposition: SessionDisposition
    automatic_titles = True
    controller: AgentController | None = None
    """The ACP controller, when this connection is to a live ACP agent. Unbound
    connections (NoAgentConnection) and non-ACP backends leave the default None, so
    consumers like QtPlan can read `agent.controller` as a declared attribute instead
    of probing via `getattr(agent, "controller", None)`."""

    @property
    def plan_entries(self) -> tuple:
        """The agent's current plan, as the thread sidebar's Plan panel lists it: the ACP
        controller's plan display, or no entries for a connection without one."""
        controller = self.controller
        return tuple(controller.plan_display.entries) if controller is not None else ()

    @property
    def readiness_refusal(self) -> NoLiveAgent:
        return NoLiveAgent(self.session_disposition)

    @property
    def readiness_decision(self) -> InputDecision:
        ordinary = InputAccepted() if self.ready else self.readiness_refusal
        return self.session_disposition.present(
            ordinary, lambda status: self.readiness_refusal
        )

    @property
    def committed_native_output(self) -> CommitSource:
        return CommitSource()

    async def observe_thread_presentation(self, presentation: ThreadPresentation) -> None:
        """Consume a published canonical change; unmanaged/unbound connections need no binding."""

    @abstractmethod
    def matches_session(self, session_id: AcpSessionId) -> bool: ...

    @abstractmethod
    def borrowed_processes(self): ...

    @abstractmethod
    async def reconnect_session(self, source: MainScreen, plan: ExistingSessionLoadPlan) -> None: ...

    def thread_read(self):

        return ThreadRead()

    def model_info(self, session_name: str) -> str:
        """The info bar's agent text: the selected model and thinking level, else the session."""
        model = self.configuration.model.selected
        if model is None:
            return session_name
        level = self.configuration.thinking.current
        return model.name + (f" · {level}" if level else "")

    @abstractmethod
    def attach_view(self, view: ConversationSessionBinding) -> None: ...

    @abstractmethod
    def refresh_projection(self, view: ConversationSessionBinding) -> None: ...

    @abstractmethod
    def start_session(self, view: ConversationSessionBinding) -> None: ...

    @abstractmethod
    def start_agent(self, sources: OperationalSessionSources, view: Conversation) -> None: ...

    @abstractmethod
    def update_view(self, view: ConversationSessionBinding) -> None: ...

    @abstractmethod
    def connected(self, view: ConversationSessionBinding) -> None: ...

    @abstractmethod
    def accepts_message(self, message: Publication) -> bool: ...

    @abstractmethod
    def begin_submission(self, owner: ConversationSubmissions, submission: AgentInputSubmission) -> SubmissionStart: ...

    @abstractmethod
    def accepts_failed_input(self, message: Publication) -> bool: ...

    goal_control_refusal: ClassVar[str] = "Persistent goals require an agent-comms session"

    async def get_goal_history(self, goal_id: GoalId) -> RecordedGoalHistory:
        return RecordedGoalHistory.empty()

    async def edit_goal(self, goal: Goal, text: str) -> Goal:
        raise GoalRefused(self.goal_control_refusal)

    async def update_goal(self, action: type[GoalAction], text: str = "") -> GoalDeclaration:
        raise GoalRefused(self.goal_control_refusal)


class NoAgentConnection(AgentConnection):
    """A real saved view before it acquires any native connection."""

    ready = False
    available_modes = ()
    current_mode = None
    session_disposition = UnopenedSessionDisposition()

    @cached_property
    def events(self):
        return CoreEventStream(self)

    @cached_property
    def presentation(self):
        return LocalAgentPresentation(self)

    @cached_property
    def configuration(self):
        return AgentConfiguration(self)

    def get_info(self) -> str:
        return ""

    async def retire_surface(self, view: Conversation) -> None:
        """There is no native surface to retire."""

    def attach_view(self, view: ConversationSessionBinding) -> None:
        """There is no event stream to subscribe to."""

    def refresh_projection(self, view: ConversationSessionBinding) -> None:
        """There is no native projection to read."""

    def start_session(self, view: ConversationSessionBinding) -> None:
        view.start_unbound_session()

    def start_agent(self, sources: OperationalSessionSources, view: Conversation) -> None:
        sources.create_agent(view)

    def update_view(self, view: ConversationSessionBinding) -> None:
        view.show_agent_info("shell")

    def connected(self, view: ConversationSessionBinding) -> None:
        """There is no connected-agent notification."""

    async def set_session_name(self, name: str) -> None:
        """A view can have a title before acquiring its native session."""

    async def stop(self) -> None:
        """There is no agent process to stop."""

    def detach_surface(self, view: Conversation) -> None:
        """There is no agent subscription to detach."""

    def accepts_message(self, message: Publication) -> bool:
        return False

    def matches_agent(self, agent) -> bool:
        return False

    async def get_goal_snapshot(self) -> GoalSnapshot:
        return GoalSnapshot(NoGoal(), IdleGoalExecution())

    async def project_changed(self, path: Path) -> None:
        """There is no native session project to persist."""

    def refresh_context(self, view: Conversation) -> None:
        """There is no native measurement to display."""

    async def set_model(self, model_id: str) -> str:
        return "No agent is bound yet"

    async def set_mode(self, mode_id: str) -> str:
        return "No agent is bound yet"

    async def compact_context(self, instructions) -> None:
        """No native context exists to compact."""

    async def cancel_turn(self, view: Conversation) -> None:
        """No native turn exists to cancel."""

    def begin_submission(self, owner: ConversationSubmissions, submission: AgentInputSubmission):
        return owner.unbound(submission, self.readiness_refusal)

    def accepts_failed_input(self, message: Publication) -> bool:
        return False

    def cancel_allowed(self, turn: TurnOwner) -> bool:
        return False

    async def cancel(self) -> bool:
        return False

    def matches_session(self, session_id: AcpSessionId) -> bool:
        return False

    def borrowed_processes(self):
        return ()

    async def reconnect_session(self, source: MainScreen, plan: ExistingSessionLoadPlan) -> None:
        source.presentation.sources.attach_started(source, plan)

    async def change_project(self, view: Conversation, path: Path) -> None:
        view.flash_error("Project changes require an agent-comms session")

    def request_compaction(self, view: Conversation, instructions) -> None:
        view.flash_error("Context compaction requires an agent-comms session")

    def invalidate_observation(self, observation: SessionObservation) -> None:
        """No native source exists to schedule a read against."""
