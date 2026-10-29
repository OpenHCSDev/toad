"""Source-owned queue capabilities; the prompt is their one presentation consumer.

These are read-only views of existing attachments, transport and notification
proofs. They never reserve input, keep membership, or turn BUS references into
ACP request identities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from acp.exceptions import RequestError
from agent_comms.acp_extension import NoQueueScope, QueueItem
from agent_comms.message_reference import MessageReference
from agent_comms.ui_model.observation import ReadNotifications
from textual import on
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static

from toad.line_blocks import MutedRole, Span, SpanColumns
from toad.notification_status import DetailLines, NotificationStatus
from toad.screens.modal import DismissibleScreen
from toad.widgets.tool_content import ToolContent

if TYPE_CHECKING:
    from agent_comms.acp_extension import QueueScope
    from toad.conversation_submission import ConversationSubmissions


class QueueEvidenceChanged(Message):
    """Local repaint after existing notification/viewport evidence changes."""


@dataclass(frozen=True)
class MessageQueueEntry:
    request: ReadNotifications
    status: NotificationStatus

    @property
    def reference(self) -> MessageReference:
        return self.request.references[0]

    @property
    def summary(self) -> str:
        return f"{self.reference.seq}: {self.status.queue_title}"

    @property
    def details(self) -> DetailLines:
        return (
            (Span(f"{self.request.root} · {self.reference.seq}/{self.reference.message_id}", MutedRole),),
            *self.status.queue_details,
        )


class QueueSource:
    """An absent source grants neither queue membership nor mutation authority."""

    preview_limit = 3

    def queue_summary(self, owner: ConversationSubmissions) -> str:
        return "Queue unavailable"

    def queue_details(self, owner: ConversationSubmissions) -> DetailLines:
        return ((Span("No queue observation is available for this source.", MutedRole),),)


class ReadOnlyQueueSource(QueueSource):
    """A source may expose delivery evidence without granting native actions."""

    def queue_scope(self, owner: ConversationSubmissions) -> QueueScope:
        return NoQueueScope()

    def queue_actions_available(self, owner: ConversationSubmissions) -> bool:
        return False

    async def queue_send_now(self, owner: ConversationSubmissions, scope: QueueScope) -> None:
        raise ValueError("Send now unavailable: this source has no native queue authority")

    async def queue_clear(self, owner: ConversationSubmissions, scope: QueueScope) -> None:
        raise ValueError("Clear unavailable: BUS messages cannot be withdrawn through an ACP queue")


class NativeQueueSource(QueueSource):
    """Native queue presentation and actions borrow the actual ACP attachment."""

    def queue_summary(self, owner: ConversationSubmissions) -> str:
        projection = owner.queue_projection
        feedback = projection.feedback(owner.view.agent_binding.presentation.queue_supported)
        parts = [feedback] if feedback else []
        for label, texts, detail in (
            ("Submitting", tuple(QueueItem.summarize(text) for text in owner.delivering), ""),
            ("Queued", tuple(row.preview for row in projection.items), ""),
            ("Restored", tuple(row.preview for row in projection.restored), ", read-only"),
        ):
            if texts:
                parts.append(f"{label} ({len(texts)}{detail}): " + " · ".join(texts[:self.preview_limit]))
        return " | ".join(parts)

    def queue_details(self, owner: ConversationSubmissions) -> DetailLines:
        agent = owner.view.agent_binding
        projection = owner.queue_projection
        lines = [(Span("Submitting is local intent; Queued is producer acceptance, not consumption.", MutedRole),)]
        lines.extend((Span(f"Submitting: {QueueItem.summarize(text)}", MutedRole),)
                     for text in owner.delivering)
        lines.extend((Span(f"Queued {row.input_id}: {row.preview}", MutedRole),)
                     for row in projection.items)
        lines.extend((Span(f"Restored {row.input_id} (read-only): {row.preview}", MutedRole),)
                     for row in projection.restored)
        lines.append((Span(agent.presentation.queue_identity, MutedRole),))
        return tuple(lines)

    def queue_scope(self, owner: ConversationSubmissions) -> QueueScope:
        return owner.view.agent_binding.presentation.queue_scope

    def queue_actions_available(self, owner: ConversationSubmissions) -> bool:
        return owner.view.agent_binding.presentation.queue_actions_available

    def require_queue_action(self, owner: ConversationSubmissions, scope: QueueScope):
        return owner.view.agent_binding.presentation.require_queue_action(scope)

    async def queue_send_now(self, owner: ConversationSubmissions, scope: QueueScope) -> None:
        agent = self.require_queue_action(owner, scope)
        if not await agent.controller.send_now():
            raise ValueError("The native owner did not accept send now")

    async def queue_clear(self, owner: ConversationSubmissions, scope: QueueScope) -> None:
        await self.require_queue_action(owner, scope).controller.clear_queue()


class BusQueueSource(ReadOnlyQueueSource):
    """BUS views borrow original-reference/per-recipient evidence, not ACP rows."""

    def queue_summary(self, owner: ConversationSubmissions) -> str:
        entries = owner.message_queue_entries
        transport = owner.view.send_block_reason
        evidence = " · ".join(entry.summary for entry in entries[:self.preview_limit])
        coverage = f"Delivery ({len(entries)} visible messages)"
        return " | ".join(part for part in (transport, coverage + (f": {evidence}" if evidence else ": unobserved")) if part)

    def queue_details(self, owner: ConversationSubmissions) -> DetailLines:
        return (
            (Span("Visible original message references only; this is not an ACP queue or a complete inbox count.", MutedRole),),
            (Span(owner.view.send_block_reason, MutedRole),),
            (Span(f"Showing up to {self.preview_limit} visible messages and their leading observed recipient; not complete recipient coverage.", MutedRole),),
            *(line for entry in owner.message_queue_entries[:self.preview_limit] for line in entry.details),
            (Span("Clear/send-now unavailable: this BUS source has no native queue authority.", MutedRole),),
        )


class QueueInspection(DismissibleScreen[None]):
    """One inspect/action surface for native, channel and bridge composers."""

    DEFAULT_CSS = """
    QueueInspection { align: center middle; background: $background 40%; }
    QueueInspection > Vertical { width: 85%; max-width: 110; height: 75%; padding: 1 2; background: $surface; }
    QueueInspection VerticalScroll { height: 1fr; }
    QueueInspection HorizontalGroup { height: auto; }
    QueueInspection #queue-error { height: auto; color: $error; }
    """

    def __init__(self, owner: ConversationSubmissions):
        super().__init__()
        self.submissions = owner
        self.source = owner.queue_source
        self.agent = owner.view.agent_binding
        self.scope = self.source.queue_scope(owner)

    def compose(self):
        with Vertical():
            yield Static("Queue and delivery")
            with VerticalScroll():
                details = ToolContent()
                details.update((SpanColumns(self.source.queue_details(self.submissions)),))
                yield details
            yield Static("Individual edit/delete/reorder requires ID-targeted, revision-checked backend support.")
            yield Static("", id="queue-error")
            with HorizontalGroup():
                available = self.source.queue_actions_available(self.submissions)
                yield Button("Send now", id="queue-send-now", disabled=not available)
                yield Button("Clear queued inputs", id="queue-clear", disabled=not available)
                yield Button("Close", id="queue-close")

    async def apply_action(self, action):
        try:
            if self.submissions.queue_source is not self.source or self.submissions.view.agent_binding is not self.agent:
                raise ValueError("The source changed; inspect its current queue again")
            await action(self.submissions, self.scope)
        except (ValueError, RequestError) as error:
            self.query_one("#queue-error", Static).update(str(error))
            return
        self.submissions.publish_pending()
        self.dismiss()

    @on(Button.Pressed, "#queue-send-now")
    async def send_now(self):
        await self.apply_action(self.source.queue_send_now)

    @on(Button.Pressed, "#queue-clear")
    async def clear_queue(self):
        await self.apply_action(self.source.queue_clear)

    @on(Button.Pressed, "#queue-close")
    def close_queue(self):
        self.dismiss()
