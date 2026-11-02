"""Source-bound submission capabilities and one queue presentation workflow."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from acp.exceptions import RequestError
from agent_comms.acp_extension import NoQueueScope, QueueItem, QueueScope
from agent_comms.comms import Comms
from agent_comms.errors import RelationViolationError, RouteChangedError, UnregisteredThreadError
from agent_comms.frozen_recipient import FrozenRecipient
from agent_comms.messages import Message
from agent_comms.runtime_requests import ClearQueueRuntimeRequest, QueueActionRuntimeRequest, SendNowRuntimeRequest

from toad.acp.queue_attachment import QueueActionRefused
from toad.conversation_submission import PromptInputSubmission, ConversationSubmissions, SubmissionStart
from toad.input_decision import InputAccepted, InputDecision, InputSourceUnavailable
from toad.line_blocks import MutedRole, Span
from toad.notification_status import DetailLines
from toad.queue_capability import QueueActions, QueueEvidence

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation


class QueueSource(QueueActions):
    """The captured source controls sending, observation and queue changes."""

    preview_limit: ClassVar[int] = 3

    def capture_queue_service(self, view: Conversation) -> Callable[[], Comms]:
        return view.app.coordination_access.observation.queue_service

    def send_now_available(self, owner: ConversationSubmissions) -> bool:
        return self.queue_actions_available(owner.queue_evidence)

    def begin_submission(self, owner: ConversationSubmissions,
                         submission: PromptInputSubmission) -> SubmissionStart:
        return owner.unbound(submission, InputSourceUnavailable())

    def input_decision(self, view: Conversation) -> InputDecision:
        return InputSourceUnavailable()

    def defers_input(self, view: Conversation) -> bool:
        return False

    def contains_message(self, view: Conversation, root: Path, sent: Message) -> bool:
        """Only the original message source can confirm its committed row."""
        return False

    def queue_summary(self, evidence: QueueEvidence) -> str:
        local = evidence.delivering
        submitting = (f"Submitting ({len(local)}): " + " · ".join(
            QueueItem.summarize(text) for text in local[:self.preview_limit])) if local else ""
        return " | ".join(part for part in (
            evidence.transport, submitting, self.observed_summary(evidence)) if part)

    def observed_summary(self, evidence: QueueEvidence) -> str:
        return "Queue unavailable"

    def queue_details(self, evidence: QueueEvidence) -> DetailLines:
        lines: list[tuple[Span, ...]] = [(Span("Submitting is local intent; acceptance is not consumption.", MutedRole),)]
        lines.extend((Span(f"Submitting: {QueueItem.summarize(text)}", MutedRole),)
                     for text in evidence.delivering)
        if evidence.transport:
            lines.append((Span(evidence.transport, MutedRole),))
        lines.extend(self.observed_details(evidence))
        return tuple(lines)

    def observed_details(self, evidence: QueueEvidence) -> DetailLines:
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
    def send_now_available(self, owner: ConversationSubmissions) -> bool:
        return self.defers_input(owner.view) and super().send_now_available(owner)

    def begin_submission(self, owner: ConversationSubmissions,
                         submission: PromptInputSubmission) -> SubmissionStart:
        return owner.view.agent_binding.begin_submission(owner, submission)

    def defers_input(self, view: Conversation) -> bool:
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

    def input_decision(self, view: Conversation) -> InputDecision:
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
