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


@dataclass(frozen=True)
class SessionBinding:
    """Actual ACP binding identity, preserved only until session replacement."""
    session_id: str | None

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
        from agent_comms.acp_extension import TranscriptSnapshotUpdate
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
            binding.post(CommsUpdated(agent.coordination, agent, agent.session_id))
            page = await agent.get_transcript_page()
            if self.surface is not binding:
                return
            if self.session is not session:
                return
            binding.post(CommsUpdated(TranscriptSnapshotUpdate(page), agent, agent.session_id))
        target = binding.target
        if target is not None:
            target.call_later(self.start_terminal_presentation, target)



    def connection_closed(self):
        from .messages import McpClientStopped
        agent = self.agent
        agent._connected_ok = False
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
