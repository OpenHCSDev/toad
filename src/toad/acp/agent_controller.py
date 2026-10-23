"""ACP operations remain owned by the controller after their view retires."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING

from acp.exceptions import RequestError
from agent_comms.acp_extension import (
    ClearQueueRequest,
    CompactRequest,
    CoordinationChangedUpdate,
    InputFailedUpdate,
    PromptRequest,
    QueuePromptRequest,
    SendNowRequest,
    encode_request,
)
from agent_comms.acp_failure import ACPFailure, RequestFailure
from agent_comms.transcripts import TranscriptReadIdentity
from agent_comms.ui_model.delivery import InputDelivery
from agent_comms.ui_model.observation import ReadInputDelivery

from toad.acp.client_session import ClientSessionRequest
from toad.acp.status import StopReason
from toad.core import events as core_events
from toad.core.events import LogAgentFail
from toad.plan import PlanItem
from toad.surface_binding import DetachedSurfaceBinding, SurfaceBinding

from .prompt import build as build_prompt
from .terminal_owner import OperationalTerminalOwner
from .transcript_reader import CoordinationTranscriptReader

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine
    from pathlib import Path

    from acp.schema import AvailableCommand
    from agent_comms.acp_extension import QueueScope, TranscriptSnapshotUpdate
    from pydantic import JsonValue

    from toad.acp.agent import Agent
    from toad.core.events import AgentFail
    from toad.render_backend import Renderer, RenderTask


@dataclass(frozen=True)
class SessionBinding:
    """Actual ACP binding identity, preserved only until session replacement."""

    session_id: str | None

    @property
    def bound(self) -> bool:
        return self.session_id is not None

    def accepts_notification(self, session_id: str):
        return self.bound and self.session_id == session_id

    def accepts_snapshot(
        self, identity: TranscriptReadIdentity, coordination: CoordinationChangedUpdate | None
    ) -> bool:
        if not self.accepts_notification(identity.requested_name) or coordination is None:
            return False
        return identity.root == coordination.wire_root and identity.thread.incarnation == coordination.thread


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
        self.coordination = None
        self.session = SessionBinding(None)
        self.commands = []
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
        from toad.core.events import AvailableCommandsUpdate, CommsUpdated

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
        if agent.coordination is not None:
            # The conversation's own refresh reads its history; this only reports the thread.
            self.agent.events.publish(CommsUpdated(agent.coordination, agent.session_id))
        binding.schedule_terminal_presentation(self)

    async def publish_transcript_snapshot(
        self, update: TranscriptSnapshotUpdate, binding: SurfaceBinding, session: SessionBinding
    ) -> None:
        if binding.target is None or not session.accepts_snapshot(update.identity, self.coordination):
            return  # No view or matching request owns this publication.
        snapshot = await self.transcripts.publication(update)
        if self.session is not session:
            return
        if self.surface is not binding:
            return
        if not session.accepts_snapshot(snapshot.identity, self.coordination):
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

    async def submit(self, prompt: str, *, request: PromptRequest | None = None):
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
        coordination = self.coordination
        self.prompt_in_flight += 1
        try:
            return await operation()
        finally:
            self.prompt_in_flight -= 1
            if self.prompt_in_flight == 0 and authority.current and coordination is not None:
                self.start_operation(self.reconcile_turn(coordination, authority))

    async def reconcile_turn(self, coordination: CoordinationChangedUpdate, authority: ClientSessionRequest) -> None:
        """Release snapshot ordering through a fresh read of the same owner."""
        self.require_owner(coordination, authority)
        await self.agent.thread_read().reconcile(self.transcripts)

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
    ):
        submission = asyncio.current_task() if command.defer_display else None
        if submission is not None:
            self._deferred_submissions.add(submission)
        try:
            coordination = self.coordination
            if coordination is not None:
                self.require_owner(coordination, authority)
                comms = await self.transcripts.service(coordination.wire_root)
                origin = await asyncio.to_thread(self.agent.queue_attachment.capture_human_input, comms, queue_scope)
                self.require_owner(coordination, authority)
                command = replace(command, origin=origin)
            content = await asyncio.to_thread(build_prompt, project, prompt)
            if any(block.type == "image" for block in content):
                coordinated = self.coordination is not None
                supported = coordinated or self.agent.session.supports_images
                if not supported:
                    raise ValueError("This agent owner does not support images yet; refresh it while idle.")
            return await self._prompt(content, command, authority, queue_scope)
        finally:
            if submission is not None:
                self._deferred_submissions.discard(submission)

    async def submit_blocks(self, content: list[dict[str, str]], command: ClearQueueRequest | None = None):
        agent = self.agent
        authority = ClientSessionRequest(agent, agent.session_id)
        return await self.operate(
            self._prompt_operation(
                partial(self._prompt, content, command, authority, agent.queue_attachment.scope), authority
            )
        )

    async def _prompt(self, content, command, authority: ClientSessionRequest, queue_scope: QueueScope):
        agent = self.agent

        def require():
            authority.require()
            if not agent.queue_attachment.accepts_request(queue_scope):
                raise ValueError("The queued input owner changed before submission; inspect the current queue.")

        try:
            result = await agent.process.prompt(
                agent, content, encode_request(command) if command is not None else {}, require
            )
        except RequestError as error:
            # The agent answered: this request failed and its session stays open.
            request_failure = RequestFailure.from_error(error)
            report = agent.events.publish
        except OSError as error:
            # The transport is gone, and the session with it.
            request_failure = RequestFailure(ACPFailure.from_detail(None, f"{type(error).__name__}: {error}"), False)
            report = agent.session.record_failure
        else:
            if authority.retired:
                return None
            return StopReason.member_named(result.stop_reason)
        if authority.retired:
            return None
        failure = request_failure.failure
        self._prompt_failed(
            command, authority, queue_scope, failure, report, published=request_failure.notification_published
        )
        return None

    def _prompt_failed(
        self,
        command,
        authority: ClientSessionRequest,
        queue_scope: QueueScope,
        failure: ACPFailure,
        report: Callable[[AgentFail], None],
        *,
        published: bool = False,
    ) -> None:
        agent = self.agent
        user_text = command.draft_text if command is not None else None
        if user_text:
            agent.events.publish(
                core_events.CommsUpdated(
                    InputFailedUpdate(user_text, failure),
                    recover_draft=True,
                    session_id=authority.session_id,
                    queue_scope=queue_scope,
                )
            )
        if not published:
            report(LogAgentFail(failure.title, failure.feedback, log_path=agent.presentation.log_path))

    async def clear_queue(self) -> None:
        await self.submit_blocks([{"type": "text", "text": " "}], ClearQueueRequest())

    async def send_now(self) -> bool:
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        queue_scope = self.agent.queue_attachment.scope
        if pending := tuple(self._deferred_submissions):
            await asyncio.gather(*(asyncio.shield(task) for task in pending))
        return (
            await self.operate(
                self._prompt_operation(
                    partial(self._prompt, [{"type": "text", "text": " "}], SendNowRequest(), authority, queue_scope),
                    authority,
                )
            )
            is not None
        )

    async def compact_context(self, instructions=None):
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        return await self.operate(
            self._prompt_operation(partial(self._compact_context, instructions, authority), authority)
        )

    async def _compact_context(self, instructions, authority: ClientSessionRequest):
        agent = self.agent
        try:
            response = await agent.process.prompt(
                agent, [{"type": "text", "text": " "}], encode_request(CompactRequest(instructions)), authority.require
            )
        except RequestError as error:
            failure = ACPFailure.from_error(error)
            raise ValueError(
                f"{failure.title}: {failure.detail}\n{failure.input_disposition}\n{failure.action}"
            ) from error
        authority.require()
        if response is None:
            raise ValueError("Compaction returned no result")
        consumer = agent.comms_consumer_class(agent, authority.session_id)
        await consumer.consume_metadata(response.field_meta)
        return consumer.require_compaction_update()

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
        if self.coordination is None:
            raise ValueError("This action requires an agent-comms thread.")
        from agent_comms.runtime import RuntimeProxy, socket_path

        from toad.owner_preparation import OwnerRequestContext

        coordination = self.coordination
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        self.require_owner(coordination, authority)
        comms = await self.transcripts.service(coordination.wire_root)

        def resolve():
            owner = comms.registry.require(coordination.thread.name)
            if owner.incarnation != coordination.thread:
                raise ValueError("The owner incarnation changed while preparing the request.")
            return RuntimeProxy(
                OwnerRequestContext(comms), owner.name, socket_path(comms.root, owner.require_process().pid)
            )

        proxy = await asyncio.to_thread(resolve)
        try:
            self.require_owner(coordination, authority)
            result = await proxy.request(method, **params)
            self.require_owner(coordination, authority)
            return result
        except (RuntimeError, RequestError) as error:
            raise ValueError(str(error)) from error
        finally:
            await proxy.close()

    def require_owner(self, coordination: CoordinationChangedUpdate, authority: ClientSessionRequest):
        if authority.retired or self.coordination is None:
            raise ValueError("The connected owner session retired; refresh its state.")
        if (self.coordination.wire_root, self.coordination.thread) != (coordination.wire_root, coordination.thread):
            raise ValueError("The owner identity changed while preparing the request.")

    async def input_delivery(self, *, include_history: bool = False) -> InputDelivery:
        """The owner's delivery notices, read by the observation service."""
        coordination = self.coordination
        if coordination is None:
            return InputDelivery()
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        delivery = await self.transcripts.read(
            ReadInputDelivery(coordination.wire_root, coordination.thread, include_history=include_history)
        )
        self.require_owner(coordination, authority)
        return delivery

    async def dismiss_historical_inputs(self):
        return await self.request_owner("dismiss_historical_inputs")
