"""Source-owned queue capabilities and captured evidence, independent of screens."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar

from acp.exceptions import RequestError
from agent_comms.acp_extension import NoQueueScope, QueueItem, QueueScope
from agent_comms.comms import Comms
from agent_comms.errors import RelationViolationError
from agent_comms.message_reference import MessageReference
from agent_comms.notification_assignment import NotificationSelection
from agent_comms.runtime_requests import ClearQueueRuntimeRequest, QueueActionRuntimeRequest, SendNowRuntimeRequest

from toad.acp.queue_attachment import QueueActionRefused
from toad.agent_presentation import AgentPresentation
from toad.block_navigation import ConversationEntry
from toad.line_blocks import MutedRole, Span
from toad.notification_status import DetailLines, MessageQueueEntry


@dataclass(frozen=True)
class QueueEvidence:
    """One UI read; only a BUS source asks for its visible message entries."""

    presentation: AgentPresentation
    delivering: tuple[str, ...]
    transport: str
    read_targets: Callable[[], tuple[ConversationEntry, ...]]
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
    def queued_recipients(self) -> tuple[str, ...]:
        """Each recipient still holding one of the visible messages, once."""
        return tuple(dict.fromkeys(name for entry in self.entries for name in entry.status.queued_recipients))


class QueueSource(ABC):
    """The source selects its capability; the actual presentation owns native facts."""

    preview_limit: ClassVar[int] = 3

    @abstractmethod
    def queue_scope(self, evidence: QueueEvidence) -> QueueScope: ...

    @abstractmethod
    def queue_actions_available(self, evidence: QueueEvidence) -> bool: ...

    @abstractmethod
    async def queue_send_now(self, evidence: QueueEvidence, scope: QueueScope) -> None: ...

    @abstractmethod
    async def queue_clear(self, evidence: QueueEvidence, scope: QueueScope) -> None: ...

    def queue_summary(self, evidence: QueueEvidence) -> str:
        return "Queue unavailable"

    def queue_details(self, evidence: QueueEvidence) -> DetailLines:
        return ((Span("No queue observation is available for this source.", MutedRole),),)


class NoQueueSource(QueueSource):
    """A view whose message source has not arrived yet holds no queue."""

    def queue_scope(self, evidence: QueueEvidence) -> QueueScope:
        return NoQueueScope()

    def queue_actions_available(self, evidence: QueueEvidence) -> bool:
        return False

    async def queue_send_now(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        raise QueueActionRefused("Send now unavailable: this view's messages have not loaded")

    async def queue_clear(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        raise QueueActionRefused("Clear unavailable: this view's messages have not loaded")


class NativeQueueSource(QueueSource):
    def queue_summary(self, evidence: QueueEvidence) -> str:
        presentation = evidence.presentation
        projection = presentation.queue
        feedback = projection.feedback(presentation.queue_supported)
        parts = [feedback] if feedback else []
        for label, texts, detail in (
            ("Submitting", tuple(QueueItem.summarize(text) for text in evidence.delivering), ""),
            ("Queued", tuple(row.preview for row in projection.items), ""),
            ("Restored", tuple(row.preview for row in projection.restored), ", read-only"),
        ):
            if texts:
                parts.append(f"{label} ({len(texts)}{detail}): " + " · ".join(texts[:self.preview_limit]))
        return " | ".join(parts)

    def queue_details(self, evidence: QueueEvidence) -> DetailLines:
        projection = evidence.presentation.queue
        lines = [(Span("Submitting is local intent; Queued is producer acceptance, not consumption.", MutedRole),)]
        lines.extend((Span(f"Submitting: {QueueItem.summarize(text)}", MutedRole),) for text in evidence.delivering)
        lines.extend((Span(f"Queued {row.input_id}: {row.preview}", MutedRole),) for row in projection.items)
        lines.extend((Span(f"Restored {row.input_id} (read-only): {row.preview}", MutedRole),)
                     for row in projection.restored)
        lines.append((Span(evidence.presentation.queue_identity, MutedRole),))
        return tuple(lines)

    def queue_scope(self, evidence: QueueEvidence) -> QueueScope:
        return evidence.presentation.queue_scope

    def queue_actions_available(self, evidence: QueueEvidence) -> bool:
        return evidence.presentation.queue_actions_available

    async def queue_send_now(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        evidence.presentation.require_queue_action(scope)
        await evidence.presentation.agent.controller.send_now()

    async def queue_clear(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        evidence.presentation.require_queue_action(scope)
        await evidence.presentation.agent.controller.clear_queue()


class BusQueueSource(QueueSource):
    """A channel or inbox: each recipient still holding a visible message has its own queue,
    reached through that recipient's owner exactly as the DM view reaches its agent's."""

    def queue_scope(self, evidence: QueueEvidence) -> QueueScope:
        return NoQueueScope()

    def queue_actions_available(self, evidence: QueueEvidence) -> bool:
        return bool(evidence.queued_recipients)

    async def queue_send_now(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        await self.at_owners(evidence, SendNowRuntimeRequest, "Send now")

    async def queue_clear(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        await self.at_owners(evidence, ClearQueueRuntimeRequest, "Clear")

    @staticmethod
    async def at_owners(evidence: QueueEvidence, action: type[QueueActionRuntimeRequest], title: str) -> None:
        """Ask every recipient's owner; name each one that refused."""
        comms = evidence.service()
        refused = []
        for name in evidence.queued_recipients:
            try:
                await asyncio.to_thread(action.at_owner, comms.root, comms.registry.require(name))
            except (RequestError, OSError, RelationViolationError) as error:
                refused.append(f"{name}: {error}")
        if refused:
            raise QueueActionRefused(f"{title} refused by " + "; ".join(refused))

    def queue_summary(self, evidence: QueueEvidence) -> str:
        entries = evidence.entries
        previews = " · ".join(entry.summary for entry in entries[:self.preview_limit])
        coverage = f"Delivery ({len(entries)} visible messages)"
        return " | ".join(part for part in (
            evidence.transport, coverage + (f": {previews}" if previews else ": unobserved")) if part)

    def queue_details(self, evidence: QueueEvidence) -> DetailLines:
        recipients = evidence.queued_recipients
        return (
            (Span("Visible original message references; actions reach each recipient that has not taken them yet.", MutedRole),),
            (Span(evidence.transport, MutedRole),),
            (Span(f"Showing up to {self.preview_limit} visible messages and their leading observed recipient.", MutedRole),),
            *(line for entry in evidence.entries[:self.preview_limit] for line in entry.details),
            (Span("Queued at: " + (", ".join(recipients) if recipients else "no recipient"), MutedRole),),
        )
