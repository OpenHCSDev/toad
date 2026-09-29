"""Operational ACP custody survives the retirement of a rich surface."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from weakref import ref
from dataclasses import dataclass

from agent_comms.declared_family import DeclaredFamily
from toad.render_tasks import ValidateSessionUpdateTask
from toad.plan import PlanItem
from .terminal_owner import OperationalTerminalOwner
from .transcript_reader import CoordinationTranscriptReader
from .client_session import ClientSessionRequest
from .prompt import build as build_prompt
from . import api, messages
from toad import jsonrpc
from toad.agent import LogAgentFail
from agent_comms.acp_extension import (
    PromptRequest, QueuePromptRequest, ClearQueueRequest, SendNowRequest,
    CompactRequest, InputFailedUpdate, decode_updates, encode_request,
)
from agent_comms.acp_failure import ACPFailure, BackendDeliveryFailure


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

    @abstractmethod
    def post(self, message) -> bool: ...


class DetachedSurfaceBinding(SurfaceBinding):
    def post(self, message):
        return False


class AttachedSurfaceBinding(SurfaceBinding):
    def __init__(self, target):
        self._target = ref(target)

    @property
    def target(self):
        return self._target()

    def post(self, message):
        target = self.target
        return target.post_message(message) if target is not None and not target._closing else False


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
        self.app = None
        self._deferred_submissions: set[asyncio.Task] = set()
        self.prompt_in_flight = 0
        self.transcripts = CoordinationTranscriptReader(self)
        self.coordination = None
        self.session = SessionBinding(None)
        self.modes = {}
        self.current_mode = None
        self.commands = []
        self.plan_entries: list[PlanItem] | None = None

    def bind_session(self, session_id):
        if session_id != self.session.session_id:
            self.replace_terminal_session()
            self.agent.permissions.cancel()
            self.agent.tools.reset()
            self.agent._active_turn_id = None
            self.session = SessionBinding(session_id)

    def attach(self, target):
        previous = self.surface.target
        if previous is target:
            return
        self.detach(previous)
        self.app = target.app
        self.transcripts.prepare_with(self.app.preparation)
        self.validation = ApplicationValidationOwner(self.app.render_processes)
        self.surface = AttachedSurfaceBinding(target)
        self.agent.permissions.present(target)
        if self.agent.ready:
            self.start_operation(self.restore(self.surface))
        else:
            self.start_operation(self.terminals.attach(target))

    def detach(self, target):
        if self.surface.owns(target):
            self.surface = DetachedSurfaceBinding()
            self.agent.permissions.detach(target)
            self.terminals.detach()

    async def validate(self, session_id, update, metadata):
        return await self.validation.validate(ValidateSessionUpdateTask(session_id, update, metadata))

    async def restore(self, binding):
        from .messages import CommsUpdated, SetModes, AvailableCommandsUpdate
        if self.surface is not binding:
            return
        session = self.session
        agent = self.agent
        # Retained operational facts are available now. A source read must not
        # hold modes, commands, plan, queue and cursor behind filesystem I/O.
        agent.configuration.publish()
        if self.current_mode is not None:
            binding.post(SetModes(self.current_mode, self.modes))
        binding.post(AvailableCommandsUpdate(self.commands))
        if self.plan_entries is not None:
            from .messages import Plan
            binding.post(Plan(self.plan_entries))
        agent._post_queue_view()
        agent._post_private_cursor()
        if agent.coordination is not None:
            coordination = agent.coordination
            authority = ClientSessionRequest(agent, agent.session_id)
            binding.post(CommsUpdated(coordination, agent, agent.session_id))
            snapshot = await self.transcripts.snapshot(
                coordination.wire_root, coordination.thread.name)
            if self.surface is not binding:
                return
            if self.session is not session:
                return
            self.require_owner(coordination, authority)
            binding.post(CommsUpdated(snapshot, agent, agent.session_id))
        target = binding.target
        if target is not None:
            target.call_later(self.start_terminal_presentation, target)



    async def publish_transcript_snapshot(self, update, binding, session):
        snapshot = await self.transcripts.publication(update)
        if self.session is not session:
            return
        if self.surface is not binding:
            return
        binding.post(messages.CommsUpdated(snapshot, self.agent, session.session_id))

    def connection_closed(self):
        from .messages import McpClientStopped
        agent = self.agent
        agent.session.closed()
        agent.permissions.cancel()
        agent._invalidate_attachment_views()
        agent._active_turn_id = None
        agent.post_message(McpClientStopped(agent))

    def publish_modes(self, current, modes):
        from .messages import SetModes
        self.current_mode, self.modes = current, modes
        self.agent.post_message(SetModes(current, modes))

    def publish_plan(self, entries: list[PlanItem]) -> None:
        """Keep the latest typed source value while its optional view is absent."""
        from .messages import Plan
        self.plan_entries = entries
        self.agent.post_message(Plan(entries))

    def publish_commands(self, commands):
        from .messages import AvailableCommandsUpdate
        self.commands = commands
        self.agent.post_message(AvailableCommandsUpdate(commands))

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
            content = await asyncio.to_thread(build_prompt, project, prompt)
            if any(block.get('type') == 'image' for block in content):
                coordinated = self.coordination is not None
                supported = coordinated or (self.agent.session.capabilities.get('promptCapabilities') or {}).get('image', False)
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
            failure = ACPFailure.from_error(error.code, error.message, error.data)
            self._prompt_failed(command, authority, queue_scope, failure,
                failure.title, f'{failure.detail}\n{failure.input_disposition}\n{failure.action}')
            return None
        except jsonrpc.JSONRPCError as error:
            if authority.retired:
                return None
            detail = error.message or 'Connection failed'
            self._prompt_failed(command, authority, queue_scope, BackendDeliveryFailure(detail),
                'Failed to send prompt', error.message or f"{agent._agent_data['name']} returned an error")
            return None
        if authority.retired:
            return None
        assert result is not None
        return result.get('stopReason')

    def _prompt_failed(self, command, authority, queue_scope, failure, title, detail):
        agent = self.agent
        user_text = command.draft_text if command is not None else None
        if user_text:
            agent.post_message(messages.CommsUpdated(InputFailedUpdate(user_text, failure),
                recover_draft=True, agent=agent, session_id=authority.session_id, queue_scope=queue_scope))
        agent.post_message(LogAgentFail(title, detail, log_path=agent.presentation.log_path))

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
        for fact in decode_updates(response.get('_meta')):
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
