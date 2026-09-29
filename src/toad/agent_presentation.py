"""Agent-owned optional capabilities and derived attachment presentation."""
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from agent_comms.declared_family import DeclaredFamily
from agent_comms.acp_extension import PendingQueueProjection, QueueProjection
from toad.private_native_cursor import CursorStatus
from toad.conversation_turn import TurnBinding, LocalTurnBinding, ManagedTurnBinding


@dataclass(frozen=True)
class AgentAttachmentView:
    cursor: CursorStatus | None
    cursor_sequence: int
    queue: QueueProjection
    queue_sequence: int


class AgentPresentation(DeclaredFamily, affix="AgentPresentation"):
    TURN_BINDING: type[TurnBinding]
    def __init__(self, agent):
        self.agent = agent
        self.turns = self.TURN_BINDING(agent)
        self.auth_methods = []
        self.log_path: Path | None = None

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
    def attachments(self):
        return AgentAttachmentView(None, 0, PendingQueueProjection(), 0)


class ACPAgentPresentation(AgentPresentation):
    uses_managed_turns = True
    TURN_BINDING = ManagedTurnBinding

    @property
    def prompt_in_flight(self):
        return self.agent.controller.prompt_in_flight

    @property
    def attachments(self):
        agent = self.agent
        return AgentAttachmentView(agent._private_cursor.status, agent._private_cursor_sequence,
                                   agent.queue_attachment.projection, agent._queue_sequence)
