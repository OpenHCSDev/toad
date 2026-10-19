"""The agent itself is a bound connection; a saved view may be unbound."""
from __future__ import annotations
from abc import ABC, abstractmethod
from functools import cached_property
from textual.content import Content
from toad.agent_presentation import LocalAgentPresentation
from toad.acp.agent_configuration import AgentConfiguration
from toad.acp.agent_session import UnopenedSessionDisposition


class UnboundAgentError(ValueError):
    """An operation requires a connection the view has not acquired."""


class AgentBinding(ABC):
    def model_info(self) -> Content:
        model = self.configuration.model.selected
        if model is None:
            return Content(self.get_info())
        level = self.configuration.thinking.current
        return Content(model.name + (f" · {level}" if level else ""))

    @abstractmethod
    def attach_view(self, view) -> None: ...

    @abstractmethod
    def refresh_projection(self, view) -> None: ...

    @abstractmethod
    def start_session(self, view) -> None: ...

    @abstractmethod
    def start_agent(self, sources, view) -> None: ...

    @abstractmethod
    def update_view(self, view) -> None: ...

    @abstractmethod
    def connected(self, view) -> None: ...

    @abstractmethod
    def accepts_message(self, message) -> bool: ...

    @abstractmethod
    def matches_agent(self, agent) -> bool: ...

    @abstractmethod
    def turn_projection(self): ...


class NoAgentBound(AgentBinding):
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

    def thread_read(self):
        return None

    def turn_projection(self):
        return None

    async def retire_surface(self, view) -> None:
        """There is no native surface to retire."""

    def attach_view(self, view) -> None:
        """There is no event stream to subscribe to."""

    def refresh_projection(self, view) -> None:
        """There is no native projection to read."""

    def start_session(self, view) -> None:
        view.start_unbound_session()

    def start_agent(self, sources, view) -> None:
        sources.create_agent(view)

    def update_view(self, view) -> None:
        view.agent_info = Content.styled("shell")

    def connected(self, view) -> None:
        """There is no connected-agent notification."""

    async def set_session_name(self, name: str) -> None:
        """A view can have a title before acquiring its native session."""

    async def stop(self) -> None:
        """There is no agent process to stop."""

    def detach_surface(self, view) -> None:
        """There is no agent subscription to detach."""

    def accepts_message(self, message) -> bool:
        return False

    def matches_agent(self, agent) -> bool:
        return False

    async def project_changed(self, path) -> None:
        """There is no native session project to persist."""

    def refresh_context(self, view) -> None:
        """There is no native measurement to display."""

    async def set_model(self, model_id):
        return "No agent is bound yet"

    async def set_mode(self, mode_id):
        return "No agent is bound yet"

    async def compact_context(self, instructions) -> None:
        """No native context exists to compact."""

    async def cancel_turn(self, view) -> None:
        """No native turn exists to cancel."""

    def begin_submission(self, owner, submission):
        return owner.unbound(submission)

    def accepts_failed_input(self, message):
        return False

    def send_now(self, owner):
        """No remote queue is bound."""

    def delivery_owner(self):
        raise UnboundAgentError("No connected owner.")

    def goal_editor(self):
        raise ValueError("Editing requires an agent-comms goal")

    async def get_goal_history(self, goal_id):
        return ()

    async def update_goal(self, action, text):
        raise ValueError("Persistent goals require an agent-comms session")

    def cancel_allowed(self, turn):
        return False

    async def cancel(self):
        return False

    def matches_session(self, session_id):
        return False

    def borrowed_processes(self):
        return ()

    async def reconnect_session(self, source, plan):
        source.presentation.sources.attach_started(source, plan)

    async def change_project(self, view, path):
        view.flash("Project changes require an agent-comms session", style="error")

    def request_compaction(self, view, instructions):
        view.flash("Context compaction requires an agent-comms session", style="error")

    async def observe_thread_presentation(self, presentation):
        """There is no connected agent to inform."""

    def invalidate_observation(self, observation):
        """No native source exists to schedule a read against."""
