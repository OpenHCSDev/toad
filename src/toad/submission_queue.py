"""Source-owned queue capabilities and captured evidence, independent of screens."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar

from agent_comms.acp_extension import NoQueueScope, QueueItem, QueueScope
from agent_comms.message_reference import MessageReference
from agent_comms.notification_evidence import NotificationWindow

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

    @cached_property
    def entries(self) -> tuple[MessageQueueEntry, ...]:
        entries: dict[MessageReference, MessageQueueEntry] = {}
        for target in self.read_targets():
            for entry in target.queue_entries():
                entries[entry.reference] = entry
                if len(entries) >= NotificationWindow.window_limit:
                    return tuple(entries.values())
        return tuple(entries.values())


class QueueSource(ABC):
    """The source selects its capability; the actual presentation owns native facts."""

    preview_limit: ClassVar[int] = 3

    @abstractmethod
    def queue_scope(self, presentation: AgentPresentation) -> QueueScope: ...

    @abstractmethod
    def queue_actions_available(self, presentation: AgentPresentation) -> bool: ...

    @abstractmethod
    async def queue_send_now(self, presentation: AgentPresentation, scope: QueueScope) -> None: ...

    @abstractmethod
    async def queue_clear(self, presentation: AgentPresentation, scope: QueueScope) -> None: ...

    def queue_summary(self, evidence: QueueEvidence) -> str:
        return "Queue unavailable"

    def queue_details(self, evidence: QueueEvidence) -> DetailLines:
        return ((Span("No queue observation is available for this source.", MutedRole),),)


class ReadOnlyQueueSource(QueueSource):
    """Delivery evidence grants no native queue mutation authority."""

    def queue_scope(self, presentation: AgentPresentation) -> QueueScope:
        return NoQueueScope()

    def queue_actions_available(self, presentation: AgentPresentation) -> bool:
        return False

    async def queue_send_now(self, presentation: AgentPresentation, scope: QueueScope) -> None:
        raise QueueActionRefused("Send now unavailable: this source has no native queue authority")

    async def queue_clear(self, presentation: AgentPresentation, scope: QueueScope) -> None:
        raise QueueActionRefused("Clear unavailable: BUS messages cannot be withdrawn through an ACP queue")


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

    def queue_scope(self, presentation: AgentPresentation) -> QueueScope:
        return presentation.queue_scope

    def queue_actions_available(self, presentation: AgentPresentation) -> bool:
        return presentation.queue_actions_available

    async def queue_send_now(self, presentation: AgentPresentation, scope: QueueScope) -> None:
        presentation.require_queue_action(scope)
        await presentation.agent.controller.send_now()

    async def queue_clear(self, presentation: AgentPresentation, scope: QueueScope) -> None:
        presentation.require_queue_action(scope)
        await presentation.agent.controller.clear_queue()


class BusQueueSource(ReadOnlyQueueSource):
    def queue_summary(self, evidence: QueueEvidence) -> str:
        entries = evidence.entries
        previews = " · ".join(entry.summary for entry in entries[:self.preview_limit])
        coverage = f"Delivery ({len(entries)} visible messages)"
        return " | ".join(part for part in (
            evidence.transport, coverage + (f": {previews}" if previews else ": unobserved")) if part)

    def queue_details(self, evidence: QueueEvidence) -> DetailLines:
        return (
            (Span("Visible original message references only; this is not an ACP queue or a complete inbox count.", MutedRole),),
            (Span(evidence.transport, MutedRole),),
            (Span(f"Showing up to {self.preview_limit} visible messages and their leading observed recipient; not complete recipient coverage.", MutedRole),),
            *(line for entry in evidence.entries[:self.preview_limit] for line in entry.details),
            (Span("Clear/send-now unavailable: this BUS source has no native queue authority.", MutedRole),),
        )
