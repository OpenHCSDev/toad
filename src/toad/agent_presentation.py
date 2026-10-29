"""Agent-owned optional capabilities and derived attachment presentation."""
from __future__ import annotations

from typing import TYPE_CHECKING
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from agent_comms.declared_family import DeclaredFamily
from agent_comms.acp_extension import NoQueueScope, PendingQueueProjection, QueueProjection, QueueScope
from toad.private_native_cursor import CursorStatus, HiddenCursorStatus
from toad.conversation_turn import TurnBinding, LocalTurnBinding, ManagedTurnBinding


if TYPE_CHECKING:
    from toad.acp.agent import Agent


@dataclass(frozen=True)
class AgentAttachmentView:
    cursor: type[CursorStatus]
    cursor_sequence: int


class AgentPresentation(DeclaredFamily, affix="AgentPresentation"):
    TURN_BINDING: type[TurnBinding]
    def __init__(self, agent):
        self.agent = agent
        self.turns = self.TURN_BINDING(agent)
        self.log_path: Path | None = None

    @property
    def auth_methods(self):
        return ()

    @property
    def commands(self):
        return ()

    @property
    def queue_supported(self) -> bool:
        return False

    @property
    @abstractmethod
    def queue(self):
        """The actual source owns its input queue projection."""

    @property
    def queue_scope(self) -> QueueScope:
        return NoQueueScope()

    @property
    def queue_identity(self) -> str:
        return "No live ACP queue attachment"

    @property
    def queue_actions_available(self) -> bool:
        return False

    def require_queue_action(self, scope: QueueScope) -> Agent:
        raise ValueError("No live ACP queue authority is available")

    @property
    def prompt_in_flight(self):
        return 0

    @property
    @abstractmethod
    def uses_managed_turns(self) -> bool: ...

    @property
    @abstractmethod
    def attachments(self) -> AgentAttachmentView: ...


class LocalAgentPresentation(AgentPresentation):
    uses_managed_turns = False
    TURN_BINDING = LocalTurnBinding

    @property
    def queue(self):
        return PendingQueueProjection()

    @property
    def attachments(self):
        return AgentAttachmentView(HiddenCursorStatus, 0)


class ACPAgentPresentation(AgentPresentation):
    TURN_BINDING = LocalTurnBinding

    @property
    def auth_methods(self):
        response = self.agent.process.initialization
        return response.auth_methods or () if response is not None else ()

    @property
    def commands(self):
        from toad.slash_command import AgentAdvertisedCommand
        return tuple(AgentAdvertisedCommand.from_acp(record)
                     for record in self.agent.controller.commands)

    @property
    def queue(self):
        return self.agent.queue_attachment.projection

    @property
    def queue_supported(self) -> bool:
        """Advertisement belongs to the original coordination declaration."""
        return self.agent.coordination is not None

    @property
    def queue_scope(self) -> QueueScope:
        return self.agent.queue_attachment.scope

    @property
    def queue_identity(self) -> str:
        attachment = self.agent.queue_attachment
        return attachment.state.project(
            attachment.current,
            available=lambda current: f"Scope {current.scope!r} · revision {current.revision}",
            pending="Checking queue attachment",
            unavailable="Queue attachment unavailable",
        )

    @property
    def queue_actions_available(self) -> bool:
        return self.queue_supported and self.agent.queue_attachment.accepts_request(self.queue_scope)

    def require_queue_action(self, scope: QueueScope) -> Agent:
        if not self.queue_supported or not self.agent.queue_attachment.accepts_request(scope):
            raise ValueError("Queue attachment changed or is unavailable; inspect the current queue again")
        return self.agent

    @property
    def uses_managed_turns(self):
        return self.turns.managed

    def managed_turns(self):
        if not self.turns.managed:
            self.turns = ManagedTurnBinding(self.agent)
        return self.turns

    @property
    def prompt_in_flight(self):
        return self.agent.controller.prompt_in_flight

    @property
    def attachments(self):
        agent = self.agent
        return AgentAttachmentView(agent._private_cursor.status, agent._private_cursor_sequence)
