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


class AgentPresentation(DeclaredFamily, affix="AgentPresentation"):
    TURN_BINDING: type[TurnBinding]
    def __init__(self, agent):
        self.agent = agent
        self.turns = self.TURN_BINDING(agent)
        self.auth_methods = []
        self.log_path: Path | None = None

    @property
    @abstractmethod
    def queue(self):
        """The actual source owns its input queue projection."""

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
    def queue(self):
        return PendingQueueProjection()

    @property
    def attachments(self):
        return AgentAttachmentView(None, 0)

    async def restore_saved_history(self, view):
        view.resume_retained_history()


class ACPAgentPresentation(AgentPresentation):
    TURN_BINDING = LocalTurnBinding

    @property
    def queue(self):
        return self.agent.queue_attachment.projection

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

    async def restore_saved_history(self, view):
        # ACP readiness does not imply agent-comms routing. A generic SDK peer
        # retains its actual view; a bound comms source owns native history reads.
        if self.agent.transcript_ready:
            await view.transcript.restore_native(self.agent)
        else:
            view.resume_retained_history()
