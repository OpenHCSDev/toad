"""The operational ACP agent contract, independent of its concrete implementation.

Resources retain their own identities and lifetimes. These inherited declarations
name what their consumers use; no controller, session or process is constructed here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from agent_comms.acp_extension import CoordinationChangedUpdate, InputStartedUpdate

from toad import agent_presentation, agent_schema
from toad.core import events as core_events
from toad.acp import (
    agent_configuration, agent_controller, agent_process, agent_session,
    client_files, client_session, comms_updates, context_measurement as context_usage,
    coordination_attachment as coordination, permission_controller, projection_attachment,
    queue_attachment as queues, session_updates, thread_read as thread_reads, tool_calls,
)


class SessionAgent(ABC):
    """An ACP agent supplies resources; those resources never borrow a concrete Agent."""

    definition: agent_schema.AgentDefinition
    project_root_path: Path
    events: core_events.CoreEventStream
    process: agent_process.AgentProcess
    session: agent_session.AgentSession
    controller: agent_controller.AgentController
    permissions: permission_controller.PermissionController
    files: client_files.FileClientRequestOwner
    updates: session_updates.SessionNotificationOwner
    tools: tool_calls.SessionToolCalls
    coordination_attachment: coordination.CoordinationAttachment
    queue_attachment: queues.QueueAttachment
    context_measurement: context_usage.ContextMeasurement
    _private_cursor: projection_attachment.CursorAttachment
    _private_cursor_sequence: int
    comms_consumer_class: ClassVar[type[comms_updates.CommsUpdateConsumer]]

    @property
    @abstractmethod
    def presentation(self) -> agent_presentation.OperationalAgentPresentation: ...

    @property
    @abstractmethod
    def configuration(self) -> agent_configuration.AgentConfiguration: ...

    @property
    @abstractmethod
    def ready(self) -> bool: ...

    @abstractmethod
    async def start(self, processes: tuple[agent_process.AgentProcess, ...] = ()) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def log(self, line: str) -> None: ...

    @abstractmethod
    def thread_read(self) -> thread_reads.ThreadRead: ...

    @abstractmethod
    def _post_private_cursor(self) -> None: ...

    @abstractmethod
    def _post_queue_view(self, starts: tuple[InputStartedUpdate, ...] = ()) -> None: ...

    @abstractmethod
    def _invalidate_attachment_views(self) -> None: ...

    @abstractmethod
    def update_status_line(self) -> None: ...

    @abstractmethod
    def configuration_refusal(self, label: str) -> str: ...

    @abstractmethod
    def receive_coordination(self, update: CoordinationChangedUpdate,
                             authority: client_session.ClientSessionRequest) -> None: ...
