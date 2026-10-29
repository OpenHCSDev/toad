"""One queue screen over the source's actual attachment or captured BUS evidence."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import ClassVar

from acp.exceptions import RequestError
from agent_comms.acp_extension import NoQueueScope, QueueItem, QueueScope
from agent_comms.message_reference import MessageReference
from agent_comms.read_basis import DisplayIdentity, NoDisplaySelection
from textual import on
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static

from toad.acp.queue_attachment import QueueActionRefused
from toad.agent_presentation import AgentPresentation
from toad.line_blocks import MutedRole, Span, SpanColumns
from toad.notification_status import DetailLines, NotificationStatus
from toad.screens.modal import DismissibleScreen
from toad.widgets.tool_content import ToolContent


class QueueEvidenceChanged(Message):
    """Repaint after existing notification, viewport or transport evidence changes."""


@dataclass(frozen=True)
class MessageQueueEntry:
    reference: MessageReference
    status: NotificationStatus
    display: DisplayIdentity | NoDisplaySelection

    @property
    def summary(self) -> str:
        return f"{self.reference.seq}: {self.status.queue_title}"

    @property
    def details(self) -> DetailLines:
        return (
            (Span(f"Original {self.reference.seq}/{self.reference.message_id}", MutedRole),),
            *self.status.queue_details,
        )


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

    def queue_summary(self, presentation: AgentPresentation, delivering: tuple[str, ...],
                      entries: tuple[MessageQueueEntry, ...], transport: str) -> str:
        return "Queue unavailable"

    def queue_details(self, presentation: AgentPresentation, delivering: tuple[str, ...],
                      entries: tuple[MessageQueueEntry, ...], transport: str) -> DetailLines:
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
    def queue_summary(self, presentation: AgentPresentation, delivering: tuple[str, ...],
                      entries: tuple[MessageQueueEntry, ...], transport: str) -> str:
        projection = presentation.queue
        feedback = projection.feedback(presentation.queue_supported)
        parts = [feedback] if feedback else []
        for label, texts, detail in (
            ("Submitting", tuple(QueueItem.summarize(text) for text in delivering), ""),
            ("Queued", tuple(row.preview for row in projection.items), ""),
            ("Restored", tuple(row.preview for row in projection.restored), ", read-only"),
        ):
            if texts:
                parts.append(f"{label} ({len(texts)}{detail}): " + " · ".join(texts[:self.preview_limit]))
        return " | ".join(parts)

    def queue_details(self, presentation: AgentPresentation, delivering: tuple[str, ...],
                      entries: tuple[MessageQueueEntry, ...], transport: str) -> DetailLines:
        projection = presentation.queue
        lines = [(Span("Submitting is local intent; Queued is producer acceptance, not consumption.", MutedRole),)]
        lines.extend((Span(f"Submitting: {QueueItem.summarize(text)}", MutedRole),) for text in delivering)
        lines.extend((Span(f"Queued {row.input_id}: {row.preview}", MutedRole),) for row in projection.items)
        lines.extend((Span(f"Restored {row.input_id} (read-only): {row.preview}", MutedRole),)
                     for row in projection.restored)
        lines.append((Span(presentation.queue_identity, MutedRole),))
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
    def queue_summary(self, presentation: AgentPresentation, delivering: tuple[str, ...],
                      entries: tuple[MessageQueueEntry, ...], transport: str) -> str:
        evidence = " · ".join(entry.summary for entry in entries[:self.preview_limit])
        coverage = f"Delivery ({len(entries)} visible messages)"
        return " | ".join(part for part in (transport, coverage + (f": {evidence}" if evidence else ": unobserved")) if part)

    def queue_details(self, presentation: AgentPresentation, delivering: tuple[str, ...],
                      entries: tuple[MessageQueueEntry, ...], transport: str) -> DetailLines:
        return (
            (Span("Visible original message references only; this is not an ACP queue or a complete inbox count.", MutedRole),),
            (Span(transport, MutedRole),),
            (Span(f"Showing up to {self.preview_limit} visible messages and their leading observed recipient; not complete recipient coverage.", MutedRole),),
            *(line for entry in entries[:self.preview_limit] for line in entry.details),
            (Span("Clear/send-now unavailable: this BUS source has no native queue authority.", MutedRole),),
        )


class QueueInspection(DismissibleScreen[None]):
    """One screen captures the source, presentation and scope it actually displays."""

    DEFAULT_CSS = """
    QueueInspection { align: center middle; background: $background 40%; }
    QueueInspection > Vertical { width: 85%; max-width: 110; height: 75%; padding: 1 2; background: $surface; }
    QueueInspection VerticalScroll { height: 1fr; }
    QueueInspection HorizontalGroup { height: auto; }
    QueueInspection #queue-error { height: auto; color: $error; }
    """

    def __init__(self, source: QueueSource, presentation: AgentPresentation,
                 details: DetailLines, changed: Callable[[], None]):
        super().__init__()
        self.source, self.presentation = source, presentation
        self.scope = source.queue_scope(presentation)
        self.details, self.changed = details, changed

    def compose(self):
        with Vertical():
            yield Static("Queue and delivery")
            with VerticalScroll():
                details = ToolContent()
                details.update((SpanColumns(self.details),))
                yield details
            yield Static("Individual edit/delete/reorder requires ID-targeted, revision-checked backend support.")
            yield Static("", id="queue-error")
            with HorizontalGroup():
                available = self.source.queue_actions_available(self.presentation)
                yield Button("Send now", id="queue-send-now", disabled=not available)
                yield Button("Clear queued inputs", id="queue-clear", disabled=not available)
                yield Button("Close", id="queue-close")

    async def apply_action(self, action: Callable[[AgentPresentation, QueueScope], Awaitable[None]]) -> None:
        try:
            await action(self.presentation, self.scope)
        except (QueueActionRefused, RequestError) as error:
            self.query_one("#queue-error", Static).update(str(error))
            return
        self.changed()
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
