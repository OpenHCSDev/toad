"""Source-bound submission capabilities and one queue presentation workflow."""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from agent_comms.acp_extension import NoQueueScope, QueueItem, QueueScope
from agent_comms.messages import Message

from toad.acp.queue_attachment import QueueActionRefused
from toad.agent_presentation import AgentPresentation
from toad.conversation_submission import PromptInputSubmission, ConversationSubmissions, SubmissionStart
from toad.input_decision import InputAccepted, InputDecision, InputSourceUnavailable
from toad.line_blocks import MutedRole, Span
from toad.notification_status import DetailLines
from toad.queue_capability import QueueActions, QueueEvidence


class QueueSource(QueueActions):
    """The captured source owns admission, observation and mutation capability."""

    preview_limit: ClassVar[int] = 3

    def begin_submission(self, owner: ConversationSubmissions,
                         submission: PromptInputSubmission) -> SubmissionStart:
        return owner.unbound(submission, InputSourceUnavailable())

    def input_decision(self, view) -> InputDecision:
        return InputSourceUnavailable()

    def defers_input(self, view) -> bool:
        return False

    def draws_message(self, view, root: Path, sent: Message) -> bool:
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
        lines = [(Span("Submitting is local intent; acceptance is not consumption.", MutedRole),)]
        lines.extend((Span(f"Submitting: {QueueItem.summarize(text)}", MutedRole),)
                     for text in evidence.delivering)
        if evidence.transport:
            lines.append((Span(evidence.transport, MutedRole),))
        lines.extend(self.observed_details(evidence))
        return tuple(lines)

    def observed_details(self, evidence: QueueEvidence) -> DetailLines:
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
    def begin_submission(self, owner: ConversationSubmissions,
                         submission: PromptInputSubmission) -> SubmissionStart:
        return owner.view.agent_binding.begin_submission(owner, submission)

    def defers_input(self, view) -> bool:
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
    def input_decision(self, view) -> InputDecision:
        return InputAccepted()

    def observed_summary(self, evidence: QueueEvidence) -> str:
        entries = evidence.entries
        previews = " · ".join(entry.summary for entry in entries[:self.preview_limit])
        coverage = f"Delivery ({len(entries)} visible messages)"
        return coverage + (f": {previews}" if previews else ": unobserved")

    def observed_details(self, evidence: QueueEvidence) -> DetailLines:
        return (
            (Span("Visible original message references only; not a complete inbox count.", MutedRole),),
            (Span(f"Showing up to {self.preview_limit} visible messages and their leading observed recipient; not complete recipient coverage.", MutedRole),),
            *(line for entry in evidence.entries[:self.preview_limit] for line in entry.details),
            (Span("Clear/send-now unavailable: this BUS source has no native queue authority.", MutedRole),),
        )
