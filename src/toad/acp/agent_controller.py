"""Operational ACP custody survives the retirement of a rich surface."""
from __future__ import annotations
from toad.acp.status import StopReason
from acp.schema import SessionModeState

import asyncio
from abc import abstractmethod
from dataclasses import dataclass, replace

from agent_comms.declared_family import DeclaredFamily
from toad.acp.sdk_boundary import ValidateSessionUpdateTask
from toad.plan import PlanItem
from .terminal_owner import OperationalTerminalOwner
from .transcript_reader import DirectTranscriptReadDelivery
from .client_session import ClientSessionRequest
from .prompt import build as build_prompt
from toad.core import events as core_events
from . import api
from toad import jsonrpc
from toad.core.events import LogAgentFail
from agent_comms.acp_extension import (
    PromptRequest, QueuePromptRequest, ClearQueueRequest, SendNowRequest,
    CompactRequest, InputFailedUpdate, decode_updates, encode_request,
)
from agent_comms.acp_failure import ACPFailure, BackendDeliveryFailure, PromptFailureReceipt


@dataclass(frozen=True)
class SessionBinding:
    """Actual ACP binding identity, preserved only until session replacement."""
    session_id: str | None

    @property
    def bound(self):
        return self.session_id is not None

    def admits_notification(self, session_id):
        return self.session_id is None or self.session_id == session_id


class SurfaceBinding(DeclaredFamily, affix="SurfaceBinding"):
    target = None

    def owns(self, target):
        return self.target is target and target is not None

    def prepare(self, controller) -> None:
        """No frontend means no additional application resources to acquire."""

    def terminal_dimensions(self):
        return 80, 24

    def schedule_terminal_presentation(self, controller):
        controller.start_terminal_presentation(self.target)

    def publish_terminal(self, controller, terminal_id, execution):
        """An absent frontend does not acquire native projection work."""
        return False

    @abstractmethod
    def post(self, message) -> bool: ...

    def close(self) -> None:
        """An absent frontend has no subscription to release."""


class DetachedSurfaceBinding(SurfaceBinding):
    def post(self, message):
        return False


class ValidationOwner(DeclaredFamily, affix="ValidationOwner"):
    @abstractmethod
    async def validate(self, task): ...


class HeadlessValidationOwner(ValidationOwner):
    async def validate(self, task):
        return await asyncio.to_thread(task.execute)


class ApplicationValidationOwner(ValidationOwner):
    def __init__(self, processes):
        self.processes = processes

    async def validate(self, task):
        return await self.processes.submit(task)


class AgentController(OperationalTerminalOwner):
    """One operational source; the surface is an optional weak projection."""
    def __init__(self, agent):
        super().__init__(agent)
        self.surface: SurfaceBinding = DetachedSurfaceBinding()
        self.validation: ValidationOwner = HeadlessValidationOwner()
        self._deferred_submissions: set[asyncio.Task] = set()
        self.prompt_in_flight = 0
        self.transcripts = DirectTranscriptReadDelivery()
        self.coordination = None
        self.session = SessionBinding(None)
        self.mode_state: SessionModeState | None = None
        self.commands = []
        self.plan_entries: list[PlanItem] | None = None

    def bind_session(self, session_id):
        if session_id != self.session.session_id:
            self.replace_terminal_session()
            self.agent.permissions.cancel()
            self.agent.tools.reset()
            self.agent.presentation.turns.reset()
            self.session = SessionBinding(session_id)
            self.reset_configuration()

    def attach(self, binding: SurfaceBinding):
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

    def detach(self, target):
        if self.surface.owns(target):
            self.surface.close()
            self.surface = DetachedSurfaceBinding()
            self.agent.permissions.detach(target)
            self.terminals.detach()

    async def validate(self, session_id, update, metadata):
        return await self.validation.validate(ValidateSessionUpdateTask(session_id, update, metadata))

    async def restore(self, binding):
        from toad.core.events import CommsUpdated
        from toad.core.events import AvailableCommandsUpdate
        if self.surface is not binding:
            return
        session = self.session
        agent = self.agent
        # Retained operational facts are available now. A source read must not
        # hold modes, commands, plan, queue and cursor behind filesystem I/O.
        agent.configuration.publish()
        agent.events.publish(AvailableCommandsUpdate())
        if self.plan_entries is not None:
            from toad.core.events import Plan
            agent.events.publish(Plan(self.plan_entries))
        agent._post_queue_view()
        agent._post_private_cursor()
        if agent.coordination is not None:
            coordination = agent.coordination
            authority = ClientSessionRequest(agent, agent.session_id)
            self.agent.events.publish(CommsUpdated(coordination, agent.session_id))
            snapshot = await self.transcripts.snapshot(
                coordination.wire_root, coordination.thread.name)
            if self.surface is not binding:
                return
            if self.session is not session:
                return
            self.require_owner(coordination, authority)
            self.agent.events.publish(CommsUpdated(snapshot, agent.session_id))
        binding.schedule_terminal_presentation(self)



    async def publish_transcript_snapshot(self, update, binding, session):
        snapshot = await self.transcripts.publication(update)
        if self.session is not session:
            return
        if self.surface is not binding:
            return
        self.agent.events.publish(core_events.CommsUpdated(snapshot, session.session_id))

    def connection_closed(self):
        from toad.core.events import McpClientStopped
        agent = self.agent
        agent.session.closed()
        agent.permissions.cancel()
        agent._invalidate_attachment_views()
        agent.presentation.turns.reset()
        agent.events.publish(McpClientStopped())

    def reset_configuration(self):
        self.mode_state = None
        self.agent.configuration.reset()
        self.agent.configuration.publish()

    @property
    def available_modes(self):
        return tuple(self.mode_state.available_modes) if self.mode_state is not None else ()

    @property
    def current_mode(self):
        if self.mode_state is None:
            return None
        return next((mode for mode in self.available_modes
                     if mode.id == self.mode_state.current_mode_id), None)

    def publish_modes(self, modes: SessionModeState):
        if modes.current_mode_id not in {mode.id for mode in modes.available_modes}:
            raise ValueError("ACP mode state has no advertised current mode")
        self.mode_state = modes
        self.agent.configuration.publish()

    def update_mode(self, mode_id: str):
        if self.mode_state is None:
            raise ValueError("ACP mode update arrived without advertised modes")
        self.publish_modes(self.mode_state.model_copy(update={"current_mode_id": mode_id}))

    def publish_plan(self, entries: list[PlanItem]) -> None:
        """Keep the latest typed source value while its optional view is absent."""
        from toad.core.events import Plan
        self.plan_entries = entries
        self.agent.events.publish(Plan(entries))

    def publish_commands(self, commands):
        from toad.core.events import AvailableCommandsUpdate
        self.commands = commands
        self.agent.events.publish(AvailableCommandsUpdate())

    def start_operation(self, operation):
        return self.agent.process.start_operation(operation)

    async def operate(self, operation):
        return await asyncio.shield(self.start_operation(operation))

    async def submit(self, prompt: str, *, request: PromptRequest | None = None):
        agent = self.agent
        command = request if request is not None else QueuePromptRequest(prompt)
        return await self.operate(self._submit(
            prompt, command, ClientSessionRequest(agent, agent.session_id),
            agent.queue_attachment.scope, agent.project_root_path))

    async def _submit(self, prompt, command, authority, queue_scope, project):
        self.prompt_in_flight += 1
        submission = asyncio.current_task() if command.defer_display else None
        if submission is not None:
            self._deferred_submissions.add(submission)
        try:
            coordination = self.coordination
            if coordination is not None:
                self.require_owner(coordination, authority)
                async with self.transcripts.bind(coordination.wire_root) as comms:
                    origin = await asyncio.to_thread(
                        self.agent.queue_attachment.capture_human_input, comms, queue_scope)
                self.require_owner(coordination, authority)
                command = replace(command, origin=origin)
            content = await asyncio.to_thread(build_prompt, project, prompt)
            if any(block.type == 'image' for block in content):
                coordinated = self.coordination is not None
                supported = coordinated or self.agent.session.supports_images
                if not supported:
                    raise ValueError('This agent owner does not support images yet; refresh it while idle.')
            return await self._prompt(content, command, authority, queue_scope)
        finally:
            self.prompt_in_flight -= 1
            if submission is not None:
                self._deferred_submissions.discard(submission)

    async def submit_blocks(self, content, command=None):
        agent = self.agent
        return await self.operate(self._prompt(content, command,
            ClientSessionRequest(agent, agent.session_id), agent.queue_attachment.scope))

    async def _prompt(self, content, command, authority, queue_scope):
        agent = self.agent
        authority.require()
        if not agent.queue_attachment.accepts_request(queue_scope):
            raise ValueError('The queued input owner changed before submission; inspect the current queue.')
        with agent.request():
            pending = api.session_prompt(content, authority.session_id,
                encode_request(command) if command is not None else {})
        try:
            result = await pending.wait()
        except jsonrpc.APIError as error:
            if authority.retired:
                return None
            receipt = PromptFailureReceipt.from_error(error.code, error.message, error.data)
            failure = receipt.failure
            self._prompt_failed(command, authority, queue_scope, failure,
                failure.title, failure.feedback, published=receipt.notification_published)
            return None
        except jsonrpc.JSONRPCError as error:
            if authority.retired:
                return None
            detail = error.message or 'Connection failed'
            self._prompt_failed(command, authority, queue_scope, BackendDeliveryFailure(detail),
                'Failed to send prompt', error.message or f"{agent.definition.name} returned an error")
            return None
        if authority.retired:
            return None
        return StopReason.decode(result.stop_reason)

    def _prompt_failed(self, command, authority, queue_scope, failure, title, detail, *, published=False):
        agent = self.agent
        user_text = command.draft_text if command is not None else None
        if user_text:
            agent.events.publish(core_events.CommsUpdated(InputFailedUpdate(user_text, failure), recover_draft=True, session_id=authority.session_id, queue_scope=queue_scope))
        if not published:
            agent.events.publish(LogAgentFail(title, detail, log_path=agent.presentation.log_path))

    async def clear_queue(self):
        await self.submit_blocks([{'type': 'text', 'text': ' '}], ClearQueueRequest())

    async def send_now(self):
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        queue_scope = self.agent.queue_attachment.scope
        if pending := tuple(self._deferred_submissions):
            await asyncio.gather(*(asyncio.shield(task) for task in pending))
        return await self.operate(self._prompt(
            [{'type': 'text', 'text': ' '}], SendNowRequest(), authority, queue_scope)) is not None

    async def compact_context(self, instructions=None):
        return await self.operate(self._compact_context(
            instructions, ClientSessionRequest(self.agent, self.agent.session_id)))

    async def _compact_context(self, instructions, authority):
        agent = self.agent
        authority.require()
        with agent.request():
            pending = api.session_prompt([{'type': 'text', 'text': ' '}],
                authority.session_id, encode_request(CompactRequest(instructions)))
        try:
            response = await pending.wait()
        except jsonrpc.APIError as error:
            failure = ACPFailure.from_error(error.code, error.message, error.data)
            raise ValueError(f'{failure.title}: {failure.detail}\n{failure.input_disposition}\n{failure.action}') from error
        authority.require()
        if response is None:
            raise ValueError('Compaction returned no result')
        consumer = agent.comms_consumer_class(agent, authority.session_id)
        for fact in decode_updates(response.field_meta):
            consumer.dispatch_sync(fact)
        return consumer.require_compaction_receipt()

    async def cancel_prompt(self):
        return await self.operate(self._cancel_prompt(
            ClientSessionRequest(self.agent, self.agent.session_id)))

    async def _cancel_prompt(self, authority):
        authority.require()
        with self.agent.request():
            pending = api.session_cancel(authority.session_id, {})
        try:
            await pending.wait()
        except jsonrpc.APIError:
            return False
        return authority.current

    async def request_owner(self, method: str, **params):
        if self.coordination is None:
            raise ValueError('This action requires an agent-comms thread.')
        from agent_comms.runtime import RuntimeProxy, socket_path
        from toad.owner_preparation import OwnerRequestContext
        coordination = self.coordination
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        self.require_owner(coordination, authority)
        async with self.transcripts.bind(coordination.wire_root) as comms:
            def resolve():
                owner = comms.registry.require(coordination.thread.name)
                if owner.incarnation != coordination.thread:
                    raise ValueError('The owner incarnation changed while preparing the request.')
                return RuntimeProxy(OwnerRequestContext(comms), owner.name, socket_path(comms.root, owner.pid))
            proxy = await asyncio.to_thread(resolve)
        try:
            self.require_owner(coordination, authority)
            result = await proxy.request(method, **params)
            self.require_owner(coordination, authority)
            return result
        except (RuntimeError, jsonrpc.InvalidParams) as error:
            raise ValueError(str(error)) from error
        finally:
            await proxy.close()

    def require_owner(self, coordination, authority):
        if authority.retired or self.coordination is None:
            raise ValueError('The connected owner session retired; refresh its state.')
        if (self.coordination.wire_root, self.coordination.thread) != (coordination.wire_root, coordination.thread):
            raise ValueError('The owner identity changed while preparing the request.')

    async def input_delivery(self, *, include_history=False):
        if self.coordination is None:
            return {'inputs': [], 'historicalCount': 0, 'dismissedHistoricalCount': 0, 'historicalInputs': []}
        return await self.request_owner('input_dispositions', include_history=include_history)

    async def dismiss_historical_inputs(self):
        return await self.request_owner('dismiss_historical_inputs')

    async def unresolved_inputs(self):
        return (await self.input_delivery())['inputs']
