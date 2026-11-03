"""Connection capabilities; concrete transports own their native resources."""
from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property
from pathlib import Path
from typing import ClassVar, TYPE_CHECKING

from agent_comms.acp_extension import CompactRequest
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.errors import GoalRefused
from agent_comms.goal_history import RecordedGoalHistory
from agent_comms.goal_actions import GoalAction
from agent_comms.goals import Goal, GoalDeclaration
from agent_comms.session_load import ExistingSessionLoadPlan
from agent_comms.nominal.field_codec import GoalId
from textual.content import Content

from toad.acp.agent_configuration import AgentConfiguration
from toad.acp.session_disposition import SessionDisposition, UnopenedSessionDisposition
from toad.acp.thread_read import NoPendingThreadRead, ThreadRead
from toad.agent_presentation import AgentPresentation, LocalAgentPresentation
from toad.conversation_turn import NoTurn
from toad.compaction_view import CompactionView
from toad.session_start import SessionStartTarget
from toad.status_view import StatusView
from toad.surface_binding import SurfaceTarget
from toad.core.events import CommsUpdated
from toad.input_decision import InputDecision, InputAccepted, NoLiveAgent
from toad.widgets.committed_presentation import CommitSource

if TYPE_CHECKING:
    from toad.acp.agent_process import AgentProcess
    from toad.conversation_submission import PromptInputSubmission, ConversationSubmissions, SubmissionStart
    from toad.conversation_turn import TurnOwner
    from toad.core_event_carrier import CoreEventMessage
    from toad.session_observation import SessionObservation
    from toad.session_presentation import OperationalSessionSources
    from toad.widgets.conversation import Conversation, ConversationSessionBinding


class AgentConnection(ABC):
    """A connection defaults to no optional native capability."""

    @cached_property
    def configuration(self) -> AgentConfiguration:
        return AgentConfiguration(self)

    @cached_property
    def session_disposition(self) -> SessionDisposition:
        return UnopenedSessionDisposition()

    @property
    def ready(self) -> bool:
        return False

    @property
    def automatic_titles(self) -> bool:
        """Local sessions may take their initial title from the first prompt."""
        return True

    @property
    @abstractmethod
    def presentation(self) -> AgentPresentation: ...

    @property
    def readiness_refusal(self) -> NoLiveAgent:
        return NoLiveAgent(self.session_disposition)

    @property
    def readiness_decision(self) -> InputDecision:
        return InputAccepted() if self.ready else self.readiness_refusal

    @property
    def committed_native_output(self) -> CommitSource:
        return CommitSource()

    async def observe_thread_presentation(self, presentation: ThreadPresentation) -> None:
        """A connection without a coordinated owner has no snapshot to consume."""

    def thread_read(self) -> ThreadRead:
        return NoPendingThreadRead()

    def model_info(self, session_name: str) -> Content:
        model = self.configuration.model.selected
        if model is None:
            return Content(session_name)
        level = self.configuration.thinking.current
        return Content(model.name + (f" · {level}" if level else ""))

    @abstractmethod
    def attach_view(self, view: Conversation) -> None: ...

    @abstractmethod
    def refresh_projection(self, view: Conversation) -> None: ...

    @abstractmethod
    def start_session(self, view: ConversationSessionBinding) -> None: ...

    @abstractmethod
    def start_agent(self, sources: OperationalSessionSources, view: Conversation) -> None: ...

    @abstractmethod
    def update_view(self, view: ConversationSessionBinding) -> None: ...

    @abstractmethod
    def connected(self, view: ConversationSessionBinding) -> None: ...

    def begin_submission(self, owner: ConversationSubmissions, submission: PromptInputSubmission) -> SubmissionStart:
        return owner.unbound(submission, self.readiness_refusal)

    @abstractmethod
    def matches_agent(self, agent: object) -> bool: ...

    def accepts_publication(
        self, message: CoreEventMessage, update: CommsUpdated
    ) -> bool:
        """A connection without an ACP session never reads its publisher."""
        return False

    def borrowed_processes(self) -> tuple[AgentProcess, ...]:
        return ()

    async def reconnect_session(self, source: SessionStartTarget, plan: ExistingSessionLoadPlan) -> None:
        source.attach_started(plan)

    async def change_project(self, view: StatusView, path: Path) -> None:
        view.feedback.flash("Project changes require an agent-comms session", style="error")

    async def project_changed(self, path: Path) -> None:
        """A connection without a native session has no project row to persist."""

    def refresh_context(self, view: StatusView) -> None:
        """A connection without native measurements leaves the display unchanged."""

    def request_compaction(self, view: CompactionView, request: CompactRequest) -> None:
        view.feedback.flash("Context compaction requires an agent-comms session", style="error")

    async def compact_context(self, request: CompactRequest) -> None:
        """No native context exists to compact."""

    async def cancel_turn(self, view: Conversation) -> None:
        """No native turn exists to cancel."""

    def cancel_allowed(self, turn: TurnOwner) -> bool:
        return False

    async def cancel(self) -> bool:
        return False

    def invalidate_observation(self, observation: SessionObservation) -> None:
        """A connection without a native source schedules no observation read."""

    def get_info(self) -> str:
        return ""

    @property
    def current_turn(self):
        return NoTurn()

    def configuration_refusal(self, label: str) -> str:
        return f"This agent does not support {label} selection"

    async def set_session_name(self, name: str) -> None:
        """A connection without a native session has no remote title to change."""

    async def retire_surface(self, view: SurfaceTarget) -> None:
        """A connection without a native surface has no resources to retire."""

    def detach_surface(self, view: SurfaceTarget) -> None:
        """A connection without a native subscription has nothing to detach."""

    async def stop(self) -> None:
        """A connection without a native process has nothing to stop."""

    goal_control_refusal: ClassVar[str] = "Persistent goals require an agent-comms session"

    async def get_goal_history(self, goal_id: GoalId) -> RecordedGoalHistory:
        return RecordedGoalHistory.empty()

    async def edit_goal(self, goal: Goal, text: str) -> Goal:
        raise GoalRefused(self.goal_control_refusal)

    async def update_goal(self, action: type[GoalAction], text: str = "") -> GoalDeclaration:
        raise GoalRefused(self.goal_control_refusal)


class NoAgentConnection(AgentConnection):
    """A real saved view before it acquires any native connection."""

    @cached_property
    def presentation(self) -> AgentPresentation:
        return LocalAgentPresentation(self)

    def attach_view(self, view: Conversation) -> None:
        """There is no event stream to subscribe to."""

    def refresh_projection(self, view: Conversation) -> None:
        """There is no native projection to read."""

    def start_session(self, view: ConversationSessionBinding) -> None:
        view.start_unbound_session()

    def start_agent(self, sources: OperationalSessionSources, view: Conversation) -> None:
        sources.create_agent(view)

    def update_view(self, view: ConversationSessionBinding) -> None:
        view.agent_info = Content.styled("shell")

    def connected(self, view: ConversationSessionBinding) -> None:
        """There is no connected-agent notification."""

    def matches_agent(self, agent: object) -> bool:
        return False

    def configuration_refusal(self, label: str) -> str:
        return "No agent is bound yet"
