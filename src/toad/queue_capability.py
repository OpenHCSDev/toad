"""Captured queue evidence and mutation capability, below submission execution."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from agent_comms.acp_extension import QueueScope
from agent_comms.comms import Comms
from agent_comms.frozen_recipient import FrozenRecipient
from agent_comms.message_reference import MessageReference
from agent_comms.messages import Message
from agent_comms.notification_assignment import NotificationSelection

from toad.agent_binding import AgentConnection
from toad.agent_presentation import AgentPresentation
from toad.app_node import ToadNode
from toad.conversation_turn import ConversationTurn
from toad.input_decision import InputDecision
from toad.native_node_meta import NativeNodeMeta
from toad.notification_status import MessageQueueEntry, QueueEntries


class QueueView(ToadNode, metaclass=NativeNodeMeta):
    """The source-bound view capabilities consumed by queue policy."""

    agent_binding: AgentConnection
    turns: ConversationTurn

    @property
    def queue_observation_service(self) -> Callable[[], Comms]:
        return self.app.coordination_access.observation.queue_service

    @property
    @abstractmethod
    def native_input_decision(self) -> InputDecision: ...

    @property
    @abstractmethod
    def transcript_queue_service(self) -> Callable[[Callable[[], Comms]], Comms]: ...

    @abstractmethod
    def contains_transcript_message(self, root: Path, sent: Message) -> bool: ...

    @abstractmethod
    def contains_user_message(self, sent: Message) -> bool: ...


@dataclass(frozen=True)
class QueueEvidence:
    """One UI read; only a BUS source asks for its visible message entries."""

    presentation: AgentPresentation
    delivering: tuple[str, ...]
    transport: str
    read_targets: Callable[[], tuple[QueueEntries, ...]]
    service: Callable[[], Comms]

    @cached_property
    def entries(self) -> tuple[MessageQueueEntry, ...]:
        entries: dict[MessageReference, MessageQueueEntry] = {}
        for target in self.read_targets():
            for entry in target.queue_entries():
                entries[entry.reference] = entry
                if len(entries) >= NotificationSelection.window_limit:
                    return tuple(entries.values())
        return tuple(entries.values())

    @cached_property
    def queued_recipients(self) -> tuple[FrozenRecipient, ...]:
        return tuple(dict.fromkeys(
            recipient for entry in self.entries for recipient in entry.status.queued_recipients))


class QueueActions(ABC):
    """An exact captured source, not a queue label, grants mutation authority."""

    @abstractmethod
    def queue_scope(self, evidence: QueueEvidence) -> QueueScope: ...

    @abstractmethod
    def queue_actions_available(self, evidence: QueueEvidence) -> bool: ...

    @abstractmethod
    async def queue_send_now(self, evidence: QueueEvidence, scope: QueueScope) -> None: ...

    @abstractmethod
    async def queue_clear(self, evidence: QueueEvidence, scope: QueueScope) -> None: ...
