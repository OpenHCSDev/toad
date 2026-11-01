"""ACP operations remain owned by the controller after their view retires."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

from acp.exceptions import RequestError
from agent_comms.acp_extension import (
    ClearQueueRequest,
    CommsRequest,
    CompactRequest,
    PromptRequest,
    QueuePromptRequest,
    SendNowRequest,
    encode_request,
)
from agent_comms.transcripts import TranscriptReadIdentity
from agent_comms.ui_model.delivery import DeliveryView

from toad.acp.client_session import ClientSessionRequest, QueueSessionRequest
from toad.acp.status import PromptResult
from toad.core import events as core_events
from toad.plan import PlanItem
from toad.surface_binding import DetachedSurfaceBinding, SurfaceBinding

from toad.acp.queue_attachment import QueueActionRefused

from .prompt import build as build_prompt
from .session_output import SessionOutput
from .terminal_owner import OperationalTerminalOwner
from .transcript_reader import CoordinationTranscriptReader

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine
    from pathlib import Path

    from acp.schema import AvailableCommand
    from agent_comms.acp_extension import QueueScope, TranscriptSnapshotUpdate
    from pydantic import JsonValue

    from toad.acp.agent import Agent
    from toad.acp.coordination_attachment import CoordinationAttachment
    from toad.render_backend import Renderer, RenderTask


@dataclass(frozen=True)
class SessionBinding:
    """Actual ACP binding identity, preserved only until session replacement."""

    session_id: str | None
    output: SessionOutput = field(default_factory=SessionOutput, compare=False)

    @property
    def bound(self) -> bool:
        return self.session_id is not None

    def accepts_notification(self, session_id: str):
        return self.bound and self.session_id == session_id

    def accepts_snapshot(
        self, identity: TranscriptReadIdentity, coordination: CoordinationAttachment
    ) -> bool:
        return self.accepts_notification(identity.requested_name) and coordination.accepts_read(identity)


class TaskRunner(ABC):
    @abstractmethod
    async def run[Result](self, task: RenderTask[Result]) -> Result: ...


class ThreadTaskRunner(TaskRunner):
    async def run[Result](self, task: RenderTask[Result]) -> Result:
        return await asyncio.to_thread(task.execute)


class ProcessTaskRunner(TaskRunner):
    def __init__(self, processes: Renderer) -> None:
        self.processes = processes

    async def run[Result](self, task: RenderTask[Result]) -> Result:
        return await self.processes.submit(task)


class AgentController(OperationalTerminalOwner):
    """One operational source; the surface is an optional weak projection."""

    def __init__(self, agent: Agent, transcripts: CoordinationTranscriptReader) -> None:
        super().__init__(agent)
        self.surface: SurfaceBinding = DetachedSurfaceBinding()
        self.task_runner: TaskRunner = ThreadTaskRunner()
        self._deferred_submissions: set[asyncio.Task] = set()
        self.prompt_in_flight = 0
        self.transcripts = transcripts
        self.session = SessionBinding(None)
        self.commands: list[AvailableCommand] = []
        self.plan_entries: list[PlanItem] | None = None

    def bind_session(self, session_id) -> None:
        if session_id != self.session.session_id:
            self.replace_terminal_session()
            self.agent.permissions.cancel()
            self.agent.tools.reset()
            self.agent.presentation.turns.reset()
            self.session = SessionBinding(session_id)
            self.reset_configuration()

    def attach(self, binding: SurfaceBinding) -> None:
        previous = self.surface.target
        if self.surface.owns(binding.target):
            binding.close()
            return
        self.detach(previous)
        binding.prepare(self)
        self.surface = binding
        self.agent.permissions.present()
        if self.agent.ready:
            self.start_operation(self.restore(self.surface))
        else:
            self.start_terminal_presentation(binding.target)

    def detach(self, target) -> None:
        if self.surface.owns(target):
            self.surface.close()
            self.surface = DetachedSurfaceBinding()
            self.agent.permissions.detach(target)
            self.terminals.detach()

    async def restore(self, binding: SurfaceBinding) -> None:
        from toad.core.events import AvailableCommandsUpdate

        if self.surface is not binding:
            return
        agent = self.agent
        # Retained operational facts are available now. A source read must not
        # hold modes, commands, plan, queue and cursor behind filesystem I/O.
        agent.configuration.publish()
        agent.update_status_line()
        agent.events.publish(AvailableCommandsUpdate())
        if self.plan_entries is not None:
            from toad.core.events import Plan

            agent.events.publish(Plan(self.plan_entries))
        agent._post_queue_view()
        agent._post_private_cursor()
        # The conversation owns its history refresh; only report the attachment.
        agent.coordination_attachment.publish(agent, agent.session_id)
        binding.schedule_terminal_presentation(self)

    async def publish_transcript_snapshot(
        self, update: TranscriptSnapshotUpdate, binding: SurfaceBinding, session: SessionBinding
    ) -> None:
        if binding.target is None or not session.accepts_snapshot(update.identity, self.agent.coordination_attachment):
            return  # No view or matching request owns this publication.
        snapshot = await self.transcripts.publication(update)
        if self.session is not session:
            return
        if self.surface is not binding:
            return
        if not session.accepts_snapshot(snapshot.identity, self.agent.coordination_attachment):
            return
        self.agent.events.publish(core_events.CommsUpdated(snapshot, session.session_id))

    def connection_closed(self) -> None:
        from toad.core.events import McpClientStopped

        agent = self.agent
        agent.session.closed()
        agent.permissions.cancel()
        agent._invalidate_attachment_views()
        agent.presentation.turns.reset()
        agent.events.publish(McpClientStopped())

    def reset_configuration(self) -> None:
        self.agent.configuration.reset()
        self.agent.configuration.publish()

    def publish_plan(self, entries: list[PlanItem]) -> None:
        """Keep the latest typed source value while its optional view is absent."""
        from toad.core.events import Plan

        self.plan_entries = entries
        self.agent.events.publish(Plan(entries))

    def publish_commands(self, commands: list[AvailableCommand]) -> None:
        from toad.core.events import AvailableCommandsUpdate

        self.commands = commands
        self.agent.events.publish(AvailableCommandsUpdate())

    def start_operation[Result](self, operation: Coroutine[None, None, Result]) -> asyncio.Task[Result]:
        return self.agent.session.start_operation(operation)

    async def operate[Result](self, operation: Coroutine[None, None, Result]) -> Result:
        return await asyncio.shield(self.start_operation(operation))

    async def submit(self, prompt: str, *, request: PromptRequest | None = None) -> PromptResult:
        agent = self.agent
        command = request if request is not None else QueuePromptRequest(prompt)
        authority = ClientSessionRequest(agent, agent.session_id)
        return await self.operate(
            self._prompt_operation(
                partial(
                    self._submit, prompt, command, authority, agent.queue_attachment.scope, agent.project_root_path
                ),
                authority,
            )
        )

    async def _prompt_operation[Result](
        self, operation: Callable[[], Awaitable[Result]], authority: ClientSessionRequest
    ) -> Result:
        """Keep the request in flight until its operation ends."""
        coordination = self.agent.coordination_attachment
        self.prompt_in_flight += 1
        try:
            return await operation()
        finally:
            self.prompt_in_flight -= 1
            if self.prompt_in_flight == 0 and authority.current:
                coordination.finish_prompt(self.agent, authority)

    def accepts_turn_snapshot(self, sequence: int):
        """A remote busy turn does not imply an ordered response on this client."""
        return self.prompt_in_flight == 0 and sequence == self.agent.presentation.turns.sequence

    async def _submit(
        self,
        prompt: str,
        command: PromptRequest,
        authority: ClientSessionRequest,
        queue_scope: QueueScope,
        project: Path,
    ) -> PromptResult:
        submission = asyncio.current_task() if command.defer_display else None
        if submission is not None:
            self._deferred_submissions.add(submission)
        try:
            coordination = self.agent.coordination_attachment
            command = await coordination.prepare_command(self.agent, command, authority, queue_scope)
            content = await asyncio.to_thread(build_prompt, project, prompt)
            coordination.require_input_source(self.agent, authority)
            if any(block.type == "image" for block in content):
                if not coordination.supports_images(self.agent):
                    raise ValueError("This agent owner does not support images yet; refresh it while idle.")
            return await self._prompt(content, command, authority, queue_scope)
        finally:
            if submission is not None:
                self._deferred_submissions.discard(submission)

    async def submit_blocks(self, content: list[dict[str, str]], command: CommsRequest) -> PromptResult:
        agent = self.agent
        authority = QueueSessionRequest(agent, agent.session_id)
        return await self.operate(
            self._prompt_operation(
                partial(self._prompt, content, command, authority, agent.queue_attachment.scope), authority
            )
        )

    async def _prompt(self, content, command, authority: ClientSessionRequest, queue_scope: QueueScope) -> PromptResult:
        agent = self.agent

        def require():
            authority.require()
            if not agent.queue_attachment.accepts_request(queue_scope):
                raise QueueActionRefused("The queued input owner changed before submission; inspect the current queue.")

        outcome = await authority.prompt(content, encode_request(command), require)
        outcome.publish_failure()
        return authority.resolve(outcome)

    async def clear_queue(self) -> PromptResult:
        return await self.submit_blocks([{"type": "text", "text": " "}], ClearQueueRequest())

    async def send_now(self) -> PromptResult:
        authority = QueueSessionRequest(self.agent, self.agent.session_id)
        queue_scope = self.agent.queue_attachment.scope
        if pending := tuple(self._deferred_submissions):
            await asyncio.gather(*(asyncio.shield(task) for task in pending))
        return await self.operate(
            self._prompt_operation(
                partial(self._prompt, [{"type": "text", "text": " "}], SendNowRequest(), authority, queue_scope),
                authority,
            )
        )

    async def compact_context(self, instructions=None):
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        return await self.operate(
            self._prompt_operation(partial(self._compact_context, instructions, authority), authority)
        )

    async def _compact_context(self, instructions, authority: ClientSessionRequest):
        agent = self.agent
        outcome = await self._prompt(
            [{"type": "text", "text": " "}], CompactRequest(instructions), authority,
            agent.queue_attachment.scope,
        )
        confirmed = outcome.require_confirmation()
        authority.require()
        consumer = agent.comms_consumer_class(agent, authority.session_id)
        await consumer.consume_metadata(confirmed.response.field_meta)
        return consumer.compaction.require()

    async def cancel_prompt(self):
        return await self.operate(self._cancel_prompt(ClientSessionRequest(self.agent, self.agent.session_id)))

    async def _cancel_prompt(self, authority: ClientSessionRequest):
        authority.require()
        try:
            await self.agent.process.rpc.cancel(authority.session_id)
        except RequestError:
            return False
        return authority.current

    async def request_owner(self, method: str, **params: JsonValue):
        return await self.agent.coordination_attachment.request_owner(self.agent, method, **params)

    async def input_delivery(self, *, include_history: bool = False) -> DeliveryView:
        """The owner's delivery notices, read by the observation service."""
        return await self.agent.coordination_attachment.input_delivery(
            self.agent, include_history=include_history)

    async def dismiss_historical_inputs(self):
        return await self.request_owner("dismiss_historical_inputs")
