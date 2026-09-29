"""Operational ACP custody survives the retirement of a rich surface."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from weakref import ref

from agent_comms.declared_family import DeclaredFamily
from toad.render_tasks import ValidateSessionUpdateTask
from .terminal_owner import OperationalTerminalOwner


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
        super().__init__()
        self.agent = agent
        self.surface: SurfaceBinding = DetachedSurfaceBinding()
        self.validation: ValidationOwner = HeadlessValidationOwner()
        self.app = None
        self.coordination = None
        self.session_id = None
        self.models = {}
        self.current_model = ""
        self.modes = {}
        self.current_mode = None
        self.commands = []

    def attach(self, target):
        previous = self.surface.target
        if previous is target:
            return
        self.detach(previous)
        self.app = target.app
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
        from .messages import CommsUpdated, SetModels, SetModes, SetThinkingLevels, AvailableCommandsUpdate
        agent = self.agent
        if agent.coordination is not None:
            page = await agent.get_transcript_page()
            if self.surface is not binding:
                return
            agent.post_message(CommsUpdated(agent.coordination, agent, agent.session_id))
            agent.post_message(CommsUpdated(TranscriptSnapshotUpdate(page), agent, agent.session_id))
        if self.surface is binding:
            agent.post_message(SetModels(self.current_model, self.models))
            if self.current_mode is not None:
                agent.post_message(SetModes(self.current_mode, self.modes))
            agent.post_message(SetThinkingLevels(agent.presentation.current_thinking_level or "off", agent.presentation.thinking_levels))
            agent.post_message(AvailableCommandsUpdate(self.commands))
            agent._post_queue_view()
            agent._post_private_cursor()
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

    def publish_models(self, current, models):
        from .messages import SetModels
        self.current_model, self.models = current, models
        self.agent.post_message(SetModels(current, models))

    def publish_modes(self, current, modes):
        from .messages import SetModes
        self.current_mode, self.modes = current, modes
        self.agent.post_message(SetModes(current, modes))

    def publish_commands(self, commands):
        from .messages import AvailableCommandsUpdate
        self.commands = commands
        self.agent.post_message(AvailableCommandsUpdate(commands))

    def start_operation(self, operation):
        return self.agent.process.start_operation(operation)

    async def operate(self, operation):
        return await asyncio.shield(self.start_operation(operation))
