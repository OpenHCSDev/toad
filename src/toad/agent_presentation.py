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

    @abstractmethod
    async def restore_saved_history(self, view) -> None:
        """The source declares whether it owns a canonical saved transcript."""


class LocalAgentPresentation(AgentPresentation):
    uses_managed_turns = False
    TURN_BINDING = LocalTurnBinding

    @property
    def attachments(self):
        return AgentAttachmentView(None, 0, PendingQueueProjection(), 0)

    async def restore_saved_history(self, view):
        # The actual local presentation survives with its session-owned view.
        pass


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

    async def restore_saved_history(self, view):
        # ACP readiness does not imply agent-comms routing. A generic SDK peer
        # retains its actual view; a bound comms source owns native history reads.
        if self.agent.transcript_ready:
            await view.present_retained_native_session()
