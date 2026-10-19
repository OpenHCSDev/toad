from toad.agent_presentation import LocalAgentPresentation
from toad.agent_binding import AgentBinding
from textual.content import Content
from toad.acp.status import StopReason
from toad.conversation_turn import NoTurn
from abc import ABC, abstractmethod
from pathlib import Path
import asyncio
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

    async def reconnect_session(self, source, plan):
        await self.session.reconnect(plan)

    async def change_project(self, view, path):
        project = await self.update_project(str(path))
        view.flash(Content(f"Project changed to {project}"), style="success")

    def request_compaction(self, view, instructions):
        view.compact_context(instructions)

    def begin_submission(self, owner, submission):
        from toad.conversation_submission import SubmissionExecution
        execution = SubmissionExecution(owner, submission, self)
        owner.active.append(execution)
        return execution

    def accepts_failed_input(self, message):
        if message.publisher is not self or message.event.session_id != self.session_id:
            return False
        return (self.queue_attachment.accepts_request(message.event.queue_scope)
                if message.event.recover_draft else True)

    def send_now(self, owner):
        from functools import partial
        session, scope = self.session_id, self.queue_attachment.scope
        return owner.view.run_worker(partial(owner._send_now, self, session, scope),
                                     group='send-queued-now', exclusive=True)

    def invalidate_observation(self, observation):
        observation.revision += 1
        if not observation.active:
            observation.task = asyncio.create_task(observation._run())

    async def observe_once(self, observation, view):
        revision = observation.revision
        try:
            result = await observation.read(self)
        except observation.errors as error:
            if observation.view is not view or not view.is_attached:
                return False
            if revision != observation.revision or not view.agent_binding.matches_agent(self):
                return True
            observation.failed(view, error)
            return False
        if observation.view is not view or not view.is_attached:
            return False
        if revision != observation.revision or not view.agent_binding.matches_agent(self):
            return True
        observation.publish(view, result)
        return False

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
        view.flash("Cancelling agent turn…")
        view.turns.describe("Cancelling…")
        if view._loading is not None and view._loading.is_attached:
            view._loading.update("Cancelling…")
        if await self.cancel():
            view.flash("Turn cancelled", style="success")
        else:
            view.flash("Agent declined to cancel. Please wait.", style="error")

    def accepts_message(self, message) -> bool:
        return (not message.event.session_scoped or
                (message.publisher is self and message.event.session_id == self.session_id))

    def turn_projection(self):
        return self.presentation.turns

    def refresh_projection(self, view) -> None:
        view.status = self.context_measurement.status()
        view.turns.bound()
        view.submissions.publish_pending()
        view.delivery_observation.invalidate()

    def start_session(self, view) -> None:
        if self.ready:
            view._session_ready()

    def start_agent(self, sources, view) -> None:
        """A connected agent is not created a second time."""

    def update_view(self, view) -> None:
        view._update_model_info()
        view.status = self.context_measurement.status()
        if self.ready:
            view._session_ready()
            view.call_later(view.goal_observation.invalidate)
            view.call_later(view.delivery_observation.invalidate)

    def connected(self, view) -> None:
        view.flash(Content.assemble(self.get_info(), " connected"), style="success")
        if view._agent_data is not None:
            view.app.application.usage.publish("agent-session-begin", agent=view._agent_data.identity)

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
