"""Source-bound submission capabilities and one queue presentation workflow."""
from __future__ import annotations

import asyncio

from acp.exceptions import RequestError
from agent_comms.acp_extension import NoQueueScope, QueueScope
from agent_comms.comms import Comms
from agent_comms.errors import RelationViolationError, RouteChangedError, UnregisteredThreadError
from agent_comms.frozen_recipient import FrozenRecipient
from agent_comms.runtime_requests import ClearQueueRuntimeRequest, QueueActionRuntimeRequest, SendNowRuntimeRequest

from toad.acp.queue_attachment import QueueActionRefused
from toad.conversation_submission import PromptInputSubmission, ConversationSubmissions, SubmissionStart, QueueSource
from toad.input_decision import InputAccepted, InputDecision
from toad.line_blocks import MutedRole, Span
from toad.notification_status import DetailLines
from toad.queue_capability import QueueEvidence, QueueView


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
    def send_now_available(self, owner: ConversationSubmissions) -> bool:
        return self.defers_input(owner) and super().send_now_available(owner)

    def begin_submission(self, owner: ConversationSubmissions,
                         submission: PromptInputSubmission) -> SubmissionStart:
        return owner.agent_binding.begin_submission(owner, submission)

    def defers_input(self, view: QueueView) -> bool:
        return view.turns.owner.busy and view.agent_binding.presentation.queue_supported

    def observed_summary(self, evidence: QueueEvidence) -> str:
        presentation = evidence.presentation
        projection = presentation.queue
        feedback = projection.feedback(presentation.queue_supported)
        parts = [feedback] if feedback else []
        for label, rows, detail in (
            ("Queued", projection.items, ""),
            ("Restored", projection.restored, ", read-only"),
        ):
            if rows:
                parts.append(f"{label} ({len(rows)}{detail}): " + " · ".join(
                    row.preview for row in rows[:self.preview_limit]))
        return " | ".join(parts)

    def observed_details(self, evidence: QueueEvidence) -> DetailLines:
        projection = evidence.presentation.queue
        return (
            *((Span(f"Queued {row.input_id}: {row.preview}", MutedRole),) for row in projection.items),
            *((Span(f"Restored {row.input_id} (read-only): {row.preview}", MutedRole),)
              for row in projection.restored),
            (Span(evidence.presentation.queue_identity, MutedRole),),
        )

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
    """The channel/inbox source reaches each original recipient's own queue."""

    def send_now_available(self, owner: ConversationSubmissions) -> bool:
        # Mailbox also inherits NativeQueueSource; BUS owns this lookup choice.
        return QueueSource.send_now_available(self, owner)

    def input_decision(self, view: QueueView) -> InputDecision:
        return InputAccepted()

    def queue_scope(self, evidence: QueueEvidence) -> QueueScope:
        return NoQueueScope()

    def queue_actions_available(self, evidence: QueueEvidence) -> bool:
        return bool(evidence.queued_recipients)

    async def queue_send_now(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        await self.at_owners(evidence, SendNowRuntimeRequest, "Send now")

    async def queue_clear(self, evidence: QueueEvidence, scope: QueueScope) -> None:
        await self.at_owners(evidence, ClearQueueRuntimeRequest, "Clear")

    @staticmethod
    def at_original_owner(comms: Comms, recipient: FrozenRecipient,
                          action: type[QueueActionRuntimeRequest]) -> None:
        original = comms.registry.snapshot().born(recipient.lookup)
        action.at_owner(comms.root, original)

    @staticmethod
    async def at_owners(evidence: QueueEvidence, action: type[QueueActionRuntimeRequest], title: str) -> None:
        refused = []
        for recipient in evidence.queued_recipients:
            try:
                comms = evidence.service()
                await asyncio.to_thread(BusQueueSource.at_original_owner, comms, recipient, action)
            except (RequestError, OSError, RelationViolationError, RouteChangedError,
                    UnregisteredThreadError) as error:
                refused.append(f"{recipient.canonical_thread}: {error}")
        if refused:
            raise QueueActionRefused(f"{title} refused by " + "; ".join(refused))

    def observed_summary(self, evidence: QueueEvidence) -> str:
        entries = evidence.entries
        previews = " · ".join(entry.summary for entry in entries[:self.preview_limit])
        coverage = f"Delivery ({len(entries)} visible messages)"
        return coverage + (f": {previews}" if previews else ": unobserved")

    def observed_details(self, evidence: QueueEvidence) -> DetailLines:
        recipients = evidence.queued_recipients
        return (
            (Span("Visible original message references; actions reach their original recipients.", MutedRole),),
            (Span(f"Showing up to {self.preview_limit} visible messages and their leading observed recipient.", MutedRole),),
            *(line for entry in evidence.entries[:self.preview_limit] for line in entry.details),
            (Span("Queued at: " + (", ".join(recipient.canonical_thread for recipient in recipients)
                                  if recipients else "no recipient"), MutedRole),),
        )
