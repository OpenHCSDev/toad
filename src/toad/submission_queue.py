"""Source-owned queue capabilities and captured evidence, independent of screens."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar

from agent_comms.acp_extension import NoQueueScope, QueueScope
from agent_comms.messaging.frozen_recipient import FrozenRecipient
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.nominal.field_codec import ThreadLookup
from agent_comms.notification_assignment import NotificationSelection
from agent_comms.transport.tools.sidebar import (
    ClearQueueQueueAction,
    CommsQueueActionTool,
    QueueAction,
    SendNowQueueAction,
)

from toad.acp.queue_attachment import QueueActionRefused
from toad.agent_presentation import AgentPresentation
from toad.client.bus_submission import SubmittingTexts
from toad.client.connection import Observing
from toad.client.line_blocks import MutedRole, Span
from toad.client.notification_status import DetailLines, MessageQueueEntry


@dataclass(frozen=True)
class QueueEvidence:
    """One UI read; only a BUS source asks for its visible message entries."""

    presentation: AgentPresentation
    submitting: SubmittingTexts
    busy: bool
    read_targets: Callable[[], tuple]
    observing: Callable[[], Observing]

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
        """Each original recipient still holding a visible message, once."""
        recipients: dict[ThreadLookup, FrozenRecipient] = {}
        for entry in self.entries:
            for recipient in entry.status.queued_recipients:
                recipients.setdefault(recipient.lookup, recipient)
        return tuple(recipients.values())


class QueueSource(ABC):
    """The source selects its capability; the actual presentation owns native facts."""

    preview_limit: ClassVar[int] = SubmittingTexts.preview_limit

    def capture_queue_observing(
        self, transcript: Callable[[Callable[[], Observing]], Observing],
        observing: Callable[[], Observing],
    ) -> Callable[[], Observing]:
        return observing

    @abstractmethod
    def queue_scope(self, evidence: QueueEvidence) -> QueueScope: ...

    @abstractmethod
    def queue_actions_available(self, evidence: QueueEvidence) -> bool: ...

    @abstractmethod
    def holds_input(self, evidence: QueueEvidence) -> bool:
        """Whether Enter queues now or a queue waits to be sent: the composer shows Send now."""

    @abstractmethod
    async def queue_send_now(self, evidence: QueueEvidence, scope: QueueScope) -> None: ...

    @abstractmethod
    async def queue_clear(self, evidence: QueueEvidence, scope: QueueScope) -> None: ...

    def queue_summary(self, evidence: QueueEvidence) -> str:
        return "Queue unavailable"

    def held_count(self, evidence: QueueEvidence) -> int:
        """How many of the view's messages are still held: its own still submitting."""
        return len(evidence.submitting.texts)

    def queue_hint(self, evidence: QueueEvidence) -> str:
        """The summary's stand-in while the delivery preview is off."""
        return evidence.submitting.held_hint(self.held_count(evidence))

    def queue_details(self, evidence: QueueEvidence) -> DetailLines:
        return ((Span("No queue observation is available for this source.", MutedRole),),)


class NoQueueSource(QueueSource):
    """A view whose message source has not arrived yet holds no queue."""

    def queue_scope(self, evidence: QueueEvidence) -> QueueScope:
        return NoQueueScope()

    def queue_actions_available(self, evidence: QueueEvidence) -> bool:
        return False

    def holds_input(self, evidence: QueueEvidence) -> bool:
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
        parts.extend(evidence.submitting.summary)
        for label, texts, detail in (
            ("Queued", tuple(row.preview for row in projection.items), ""),
            ("Restored", tuple(row.preview for row in projection.restored), ", read-only"),
        ):
            if texts:
                parts.append(f"{label} ({len(texts)}{detail}): " + " · ".join(texts[:self.preview_limit]))
        return " | ".join(parts)

    def held_count(self, evidence: QueueEvidence) -> int:
        """Also the prompts the agent accepted and has not taken, and those restored to it."""
        projection = evidence.presentation.queue
        return super().held_count(evidence) + len(projection.items) + len(projection.restored)

    def queue_details(self, evidence: QueueEvidence) -> DetailLines:
        projection = evidence.presentation.queue
        lines: list[tuple[Span, ...]] = [(Span("Submitting is local intent; Queued is producer acceptance, not consumption.", MutedRole),)]
        lines.extend(evidence.submitting.details)
        lines.extend((Span(f"Queued {row.input_id}: {row.preview}", MutedRole),) for row in projection.items)
        lines.extend((Span(f"Restored {row.input_id} (read-only): {row.preview}", MutedRole),)
                     for row in projection.restored)
        lines.append((Span(evidence.presentation.queue_identity, MutedRole),))
        return tuple(lines)

    def queue_scope(self, evidence: QueueEvidence) -> QueueScope:
        return evidence.presentation.queue_scope

    def queue_actions_available(self, evidence: QueueEvidence) -> bool:
        return evidence.presentation.queue_actions_available

    def holds_input(self, evidence: QueueEvidence) -> bool:
        """A running turn takes Enter into the agent's queue."""
        return evidence.busy and evidence.presentation.queue_supported

    async def queue_send_now(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        """Send the agent's queued prompts now; with nothing queued there is nothing to send."""
        if not evidence.presentation.queue.items:
            return
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

    def holds_input(self, evidence: QueueEvidence) -> bool:
        """A message still submitting, or still held at a recipient, can be sent now."""
        return bool(evidence.submitting.texts) or self.queue_actions_available(evidence)

    async def queue_send_now(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        await self.at_owners(evidence, SendNowQueueAction)

    async def queue_clear(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        await self.at_owners(evidence, ClearQueueQueueAction)

    @staticmethod
    async def at_owners(evidence: QueueEvidence, action: type[QueueAction]) -> None:
        """Act on the original recipients; stop and propagate a failed action."""
        for recipient in evidence.queued_recipients:
            observed = evidence.observing()
            await asyncio.to_thread(
                observed.core.call, CommsQueueActionTool(lookup=recipient.lookup, action=action))

    def queue_summary(self, evidence: QueueEvidence) -> str:
        """Shown only while input is held, as a DM's queue line is: a quiet channel shows none."""
        if not self.holds_input(evidence):
            return ""
        entries = evidence.entries
        previews = " · ".join(entry.summary for entry in entries[:self.preview_limit])
        coverage = f"Delivery ({len(entries)} visible messages)"
        return " | ".join((
            *evidence.submitting.summary, coverage + (f": {previews}" if previews else ": unobserved")))

    def held_count(self, evidence: QueueEvidence) -> int:
        """Also the visible messages a recipient has not taken yet."""
        return super().held_count(evidence) + sum(
            1 for entry in evidence.entries if entry.status.queued_recipients)

    def queue_details(self, evidence: QueueEvidence) -> DetailLines:
        recipients = evidence.queued_recipients
        return (
            (Span("Visible original message references; actions reach each recipient that has not taken them yet.", MutedRole),),
            *evidence.submitting.details,
            (Span(f"Showing up to {self.preview_limit} visible messages and their leading observed recipient.", MutedRole),),
            *(line for entry in evidence.entries[:self.preview_limit] for line in entry.details),
            (Span("Queued at: " + (", ".join(recipient.canonical_thread for recipient in recipients)
                                  if recipients else "no recipient"), MutedRole),),
        )
