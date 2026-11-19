"""The queue's controls without a toolkit: Textual's `DeliveryControls`/`QueueInspection` and
Qt's `QtDeliveryControls`/`QtQueueInspection` inherit them and only draw."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import ClassVar

from acp.exceptions import RequestError
from agent_comms.acp_extension import QueueScope
from agent_comms.errors import RelationViolationError, RouteChangedError, UnregisteredThreadError
from metaclass_registry import AbstractHooksMeta

from toad.acp.queue_attachment import QueueActionRefused
from toad.client.line_blocks import SpanColumns
from toad.submission_queue import QueueEvidence


class QueueDeliveryControls:
    """The row shown while Enter queues behind a running turn: its notice and its send-now
    action's label, one spelling for both frontends."""

    notice: ClassVar[str] = "Enter queues · "
    send_now_label: ClassVar[str] = "Send now (Ctrl+Enter / Ctrl+Y)"


class QueueInspectionOwner(metaclass=AbstractHooksMeta):
    """The selected conversation's queue and delivery status, and its two actions: read from
    the submissions owner's queue source, settled by publishing the pending queue."""

    refusals = (QueueActionRefused, RequestError, RelationViolationError,
                RouteChangedError, UnregisteredThreadError)
    heading: ClassVar[str] = "Queue and delivery"
    unavailable_note: ClassVar[str] = (
        "Editing, deleting and reordering individual queued messages isn't available here.")

    def inspect_submissions(self, submissions) -> None:
        self.submissions = submissions
        self.source = submissions.view.queue_source
        self.evidence: QueueEvidence | None = submissions.queue_evidence
        self.scope: QueueScope | None = (
            None if self.evidence is None else self.source.queue_scope(self.evidence))

    @property
    def actions_available(self) -> bool:
        return self.evidence is not None and self.source.queue_actions_available(self.evidence)

    def details_block(self) -> SpanColumns:
        return SpanColumns(self.source.queue_details(self.evidence))

    async def apply_action(self, action: Callable[[QueueEvidence, QueueScope], Awaitable[None]]) -> None:
        try:
            await action(self.evidence, self.scope)
        except self.refusals as error:
            self.show_queue_error(str(error))
            return
        self.submissions.publish_pending()
        self.close_inspection()

    async def send_now(self) -> None:
        await self.apply_action(self.source.queue_send_now)

    async def clear_queue(self) -> None:
        await self.apply_action(self.source.queue_clear)

    @abstractmethod
    def show_queue_error(self, text: str) -> None:
        """Show why the queue refused the action; the actions stay offered."""

    @abstractmethod
    def close_inspection(self) -> None:
        """The action settled: close the inspection."""
