"""Agent-owned optional capabilities and derived attachment presentation."""
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from agent_comms.declared_family import DeclaredFamily
from agent_comms.acp_extension import PendingQueueProjection, QueueProjection
from toad.private_native_cursor import CursorStatus


@dataclass(frozen=True)
class AgentAttachmentView:
    cursor: CursorStatus | None
    cursor_sequence: int
    queue: QueueProjection
    queue_sequence: int


class AgentPresentation(DeclaredFamily, affix="AgentPresentation"):
    def __init__(self, agent):
        self.agent = agent
        self.auth_methods = []
        self.thinking_levels = []
        self.current_thinking_level = None
        self.prompt_in_flight = 0
        self.log_path: Path | None = None

    @property
    @abstractmethod
    def uses_managed_turns(self) -> bool: ...

    @property
    @abstractmethod
    def attachments(self) -> AgentAttachmentView: ...


class LocalAgentPresentation(AgentPresentation):
    uses_managed_turns = False

    @property
    def attachments(self):
        return AgentAttachmentView(None, 0, PendingQueueProjection(), 0)


class ACPAgentPresentation(AgentPresentation):
    uses_managed_turns = True

    @property
    def attachments(self):
        agent = self.agent
        return AgentAttachmentView(agent._private_cursor.status, agent._private_cursor_sequence,
                                   agent.queue_attachment.projection, agent._queue_sequence)
