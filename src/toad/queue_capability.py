"""Captured queue evidence and mutation capability, below submission execution."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property

from agent_comms.acp_extension import QueueScope
from agent_comms.message_reference import MessageReference
from agent_comms.notification_assignment import NotificationSelection

from toad.agent_presentation import AgentPresentation
from toad.notification_status import MessageQueueEntry, QueueEntries


@dataclass(frozen=True)
class QueueEvidence:
    """One UI read; only a BUS source asks for its visible message entries."""

    presentation: AgentPresentation
    delivering: tuple[str, ...]
    transport: str
    read_targets: Callable[[], tuple[QueueEntries, ...]]

    @cached_property
    def entries(self) -> tuple[MessageQueueEntry, ...]:
        entries: dict[MessageReference, MessageQueueEntry] = {}
        for target in self.read_targets():
            for entry in target.queue_entries():
                entries[entry.reference] = entry
                if len(entries) >= NotificationSelection.window_limit:
                    return tuple(entries.values())
        return tuple(entries.values())


class QueueActions(ABC):
    """An exact captured source, not a queue label, grants mutation authority."""

    @abstractmethod
    def queue_scope(self, presentation: AgentPresentation) -> QueueScope: ...

    @abstractmethod
    def queue_actions_available(self, presentation: AgentPresentation) -> bool: ...

    @abstractmethod
    async def queue_send_now(self, presentation: AgentPresentation, scope: QueueScope) -> None: ...

    @abstractmethod
    async def queue_clear(self, presentation: AgentPresentation, scope: QueueScope) -> None: ...
