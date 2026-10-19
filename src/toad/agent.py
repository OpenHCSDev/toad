from toad.agent_presentation import LocalAgentPresentation
from toad.agent_binding import AgentBinding
from textual.content import Content
from toad.acp.status import StopReason
from toad.conversation_turn import NoTurn
from abc import ABC, abstractmethod
from pathlib import Path
from agent_comms.thread_presentation import ThreadPresentation
from toad.core.events import CoreEventStream



class AgentBase(AgentBinding):
    """Base class for an 'agent'."""

    def __init__(self, project_root: Path) -> None:
        self.project_root_path = project_root
        self.events = CoreEventStream(self)
        self.presentation = LocalAgentPresentation(self)
        from toad.acp.agent_configuration import AgentConfiguration
        self.configuration = AgentConfiguration(self)

    ready = False

    def attach_view(self, view) -> None:
        from toad.agent_surface import AttachedSurfaceBinding
        from toad.core.events import SessionAgentAttached
        self.attach_surface(AttachedSurfaceBinding(view, self.events))
        view.publish_core(SessionAgentAttached())

    def matches_agent(self, agent) -> bool:
        return self is agent

    def delivery_owner(self):
        return self

    def goal_editor(self):
        return self

    def cancel_allowed(self, turn):
        return turn.can_cancel

    def matches_session(self, session_id):
        return self.session_id == session_id

    def borrowed_processes(self):
        return (self.process,)

    async def reconnect_session(self, source, plan):
        await self.session.reconnect(plan)

    async def change_project(self, view, path):
        project = await self.update_project(str(path))
        view.flash(Content(f"Project changed to {project}"), style="success")

    def request_compaction(self, view, instructions):
        view.compact_context(instructions)

    def begin_submission(self, owner, submission):
        return owner.start(submission, self)

    def accepts_failed_input(self, message):
        if message.publisher is not self or message.event.session_id != self.session_id:
            return False
        return (self.queue_attachment.accepts_request(message.event.queue_scope)
                if message.event.recover_draft else True)

    def send_now(self, owner):
        return owner.send_bound_now(self)

    def invalidate_observation(self, observation):
        observation.schedule()

    @property
    def automatic_titles(self):
        return self.observed_thread() is None

    async def project_changed(self, path) -> None:
        from toad.db import DB
        self.project_root_path = path
        if (session_pk := self.session.pk) is not None:
            await DB().session_update_project(session_pk, path)

    def refresh_context(self, view) -> None:
        view.status = self.context_measurement.status()

    async def compact_context(self, instructions) -> None:
        await self.controller.compact_context(instructions)

    async def cancel_turn(self, view) -> None:
        await view.cancel_bound_turn(self)

    def accepts_message(self, message) -> bool:
        return message.publisher is self and message.event.session_id == self.session_id

    def turn_projection(self):
        return self.presentation.turns

    def refresh_projection(self, view) -> None:
        view.status = self.context_measurement.status()
        view.turns.bound()
        view.submissions.publish_pending()
        view.delivery_observation.invalidate()

    def start_session(self, view) -> None:
        if self.ready:
            view.session_ready()

    def start_agent(self, sources, view) -> None:
        """A connected agent is not created a second time."""

    def update_view(self, view) -> None:
        view.apply_bound_agent(self)

    def connected(self, view) -> None:
        view.agent_connected(self)

    @property
    def session_disposition(self):
        return self.session.disposition

    @property
    def current_turn(self):
        return NoTurn()

    def attach_surface(self, binding):
        binding.close()

    async def retire_surface(self, surface):
        await self.stop()

    def observed_thread(self) -> tuple[str, str] | None:
        """The (wire root, thread name) whose status this agent shows; none without coordination."""
        return None

    def thread_read(self):
        """Agents without a coordination identity read no thread presentation."""
        return None

    async def observe_thread_presentation(self, presentation: ThreadPresentation | None) -> None:
        """Consume a published canonical change; unmanaged agents need no binding."""

    @abstractmethod
    async def send_prompt(self, prompt: str) -> type[StopReason] | None:
        """Send a prompt; return its stop reason."""

    @property
    def available_modes(self):
        return ()

    @property
    def current_mode(self):
        return None

    async def set_mode(self, mode_id: str) -> str | None:
        return "This agent does not support mode selection"

    async def cancel(self) -> bool:
        """Cancel the active prompt if supported."""
        return False

    async def set_model(self, model_id: str) -> str | None:
        return "This agent does not support model selection"

    async def set_session_name(self, name: str) -> None:
        """Set the session name.

        Args:
            name: New name for the session.
        """

    def get_info(self) -> str:
        return ""

    async def stop(self) -> None:
        """Stop the agent (gracefully exit the process)"""
