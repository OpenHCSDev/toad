"""The agent itself is a bound connection; a saved view may be unbound."""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.goal_history import RecordedGoalHistory
from textual.content import Content

from toad.acp.agent_configuration import AgentConfiguration
from toad.acp.agent_session import UnopenedSessionDisposition
from toad.agent_presentation import AgentPresentation, LocalAgentPresentation
from toad.widgets.committed_presentation import CommitSource

if TYPE_CHECKING:
    from agent_comms.goal_actions import GoalAction
    from agent_comms.session_load import ExistingSessionLoadPlan

    from toad.conversation_submission import (
        AgentInputSubmission,
        ConversationSubmissions,
        SubmissionStart,
    )
    from toad.conversation_turn import TurnOwner
    from toad.core_event_carrier import CoreEventMessage
    from toad.screens.main import MainScreen
    from toad.session_observation import SessionObservation
    from toad.session_presentation import OperationalSessionSources
    from toad.widgets.conversation import Conversation, ConversationSessionBinding


class AgentConnection(ABC):
    configuration: AgentConfiguration
    presentation: AgentPresentation

    @property
    def committed_native_output(self) -> CommitSource:
        return CommitSource()

    @abstractmethod
    async def observe_thread_presentation(self, presentation: ThreadPresentation) -> None: ...

    def thread_read(self):
        from toad.acp.comms_updates import NoPendingThreadRead

        return NoPendingThreadRead()

    def model_info(self, session_name: str) -> Content:
        model = self.configuration.model.selected
        if model is None:
            return Content(session_name)
        level = self.configuration.thinking.current
        return Content(model.name + (f" · {level}" if level else ""))

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
    def accepts_message(self, message: CoreEventMessage) -> bool: ...

    @abstractmethod
    def begin_submission(self, owner: ConversationSubmissions, submission: AgentInputSubmission) -> SubmissionStart: ...

    @abstractmethod
    def accepts_failed_input(self, message: CoreEventMessage) -> bool: ...

    @abstractmethod
    def matches_agent(self, agent) -> bool: ...


class NoAgentConnection(AgentConnection):
    """A real saved view before it acquires any native connection."""

    ready = False
    automatic_titles = True
    available_modes = ()
    current_mode = None
    session_disposition = UnopenedSessionDisposition()

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
        view.agent_info = Content.styled("shell")

    def connected(self, view: ConversationSessionBinding) -> None:
        """There is no connected-agent notification."""

    async def set_session_name(self, name: str) -> None:
        """A view can have a title before acquiring its native session."""

    async def stop(self) -> None:
        """There is no agent process to stop."""

    def detach_surface(self, view: Conversation) -> None:
        """There is no agent subscription to detach."""

    def accepts_message(self, message: CoreEventMessage) -> bool:
        return False

    def matches_agent(self, agent) -> bool:
        return False

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
        return owner.unbound(submission)

    def accepts_failed_input(self, message: CoreEventMessage) -> bool:
        return False

    async def get_goal_history(self, goal_id: str) -> RecordedGoalHistory:
        return RecordedGoalHistory.empty()

    async def update_goal(self, action: type[GoalAction], text: str):
        raise ValueError("Persistent goals require an agent-comms session")

    def cancel_allowed(self, turn: TurnOwner) -> bool:
        return False

    async def cancel(self) -> bool:
        return False

    def matches_session(self, session_id: str) -> bool:
        return False

    def borrowed_processes(self):
        return ()

    async def reconnect_session(self, source: MainScreen, plan: ExistingSessionLoadPlan) -> None:
        source.presentation.sources.attach_started(source, plan)

    async def change_project(self, view: Conversation, path: Path) -> None:
        view.feedback.flash("Project changes require an agent-comms session", style="error")

    def request_compaction(self, view: Conversation, instructions) -> None:
        view.feedback.flash("Context compaction requires an agent-comms session", style="error")

    async def observe_thread_presentation(self, presentation: ThreadPresentation) -> None:
        """There is no connected agent to inform."""

    def invalidate_observation(self, observation: SessionObservation) -> None:
        """No native source exists to schedule a read against."""
