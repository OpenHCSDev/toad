"""What is known about a message's notifications: the one-line title and the details behind it."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import ClassVar

from agent_comms.messaging.frozen_recipient import FrozenRecipient
from agent_comms.messaging.message_notification import MessageNotification
from agent_comms.messaging.message_reference import MessageReference

from toad.client.line_blocks import (
    LineBlock,
    LineLink,
    LineRole,
    MutedRole,
    NameRole,
    NoticeRole,
    OpenTarget,
    Span,
    SpanColumns,
    Summary,
    WorkingRole,
)



DetailLines = tuple[tuple[Span, ...], ...]
"""The details behind one notification state: lines of line-block spans."""


def recipient_line(recipient: str, text: str) -> tuple[Span, ...]:
    """One feedback line whose agent name opens that agent's thread.

    The name is a thread name like every drawn thread name: a ``NameRole`` span
    carrying the one link owner all of them use (``OpenTarget``, opened by
    ``OpensLinks``).
    """
    return (Span(recipient, NameRole, OpenTarget(recipient)), Span(text, MutedRole))


class ShownFragment:
    """What a reader chose about one drawn fragment, as a notification status draws it."""

    details_open: bool

    def summary(self, title: str, role: type[LineRole], link: LineLink) -> Summary:
        raise NotImplementedError


class NotificationStatus:
    """One state of the check: its one-line title and the details behind it."""

    def is_working(self) -> bool:
        return False

    def failed(self, failure: NotificationStatus) -> NotificationStatus:
        """A failed read replaces this status; a known answer stays until a new answer."""
        return failure

    @property
    def title(self) -> str:
        return ""

    @property
    def queue_title(self) -> str:
        return self.title

    @property
    def details(self) -> DetailLines:
        return ()

    @property
    def queue_details(self) -> DetailLines:
        return self.details

    @property
    def queued_recipients(self) -> tuple[FrozenRecipient, ...]:
        """Original recipients currently holding this message in their queue."""
        return ()

    @property
    def disclosure(self) -> SpanColumns:
        return SpanColumns(self.details, indent=2)

    @property
    def role(self) -> type[LineRole]:
        """The title's meaning and colour, wherever the title is drawn."""
        return WorkingRole if self.is_working() else MutedRole

    def blocks(self, shown: ShownFragment, link: LineLink) -> tuple[LineBlock, ...]:
        """The feedback row and its disclosure, shared by every message fragment."""
        summary = shown.summary(self.title, self.role, link)
        return ((summary, self.disclosure)
                if shown.details_open else (summary,))


@dataclass(frozen=True)
class MessageQueueEntry:
    reference: MessageReference
    status: NotificationStatus

    @property
    def summary(self) -> str:
        return f"{self.reference.seq}: {self.status.queue_title}"

    @property
    def details(self) -> DetailLines:
        return ((Span(f"Message #{self.reference.seq} ({self.reference.message_id})", MutedRole),),
                *self.status.queue_details)


@dataclass(frozen=True)
class UncheckedNotifications(NotificationStatus):
    # The row is drawn before Core answers, so the answer changes its text
    # instead of inserting a row under the reader.
    title = "Checking"


@dataclass(frozen=True)
class CheckedNotifications(NotificationStatus):
    notifications: tuple[MessageNotification, ...]

    @classmethod
    def for_references(cls, references: Iterable[MessageReference],
                       results: Mapping[tuple[int, str], tuple[MessageNotification, ...]]) -> Iterator[CheckedNotifications]:
        """Yield nothing when this answer has no matching reference."""
        loaded = results.keys() & {(reference.seq, reference.message_id) for reference in references}
        if loaded:
            yield cls.from_notifications(tuple(item for reference in loaded for item in results[reference]))

    @classmethod
    def from_notifications(cls, notifications: tuple[MessageNotification, ...]) -> CheckedNotifications:
        """Keep a matched empty result distinct from an observed recipient."""
        return cls(notifications) if notifications else EmptyCheckedNotifications()

    def failed(self, failure: NotificationStatus) -> NotificationStatus:
        return self

    @property
    def queued_recipients(self) -> tuple[FrozenRecipient, ...]:
        return tuple(item.recipient_identity for item in self.notifications if item.state.is_queued())

    def is_working(self) -> bool:
        return any(item.state.is_working() for item in self.notifications)

    @property
    def title(self) -> str:
        return MessageNotification.summary(self.notifications)

    @property
    def queue_title(self) -> str:
        # Keep the leading recipient's actual proof; routing is not arrival.
        first = self.notifications[0]
        return f"@{first.recipient} {first.label}"

    @property
    def queue_details(self) -> DetailLines:
        leading = CheckedNotifications.from_notifications(self.notifications[:1])
        return (
            (Span(self.title, MutedRole),),
            *((Span(f"To @{item.recipient_identity.recipient_lookup}", MutedRole),)
              for item in leading.notifications),
            *leading.details,
            *((Span(text, MutedRole),)
              for item in leading.notifications for text in item.answer.detail_texts()),
        )

    @property
    def details(self) -> DetailLines:
        lines = []
        for item in MessageNotification.ordered(self.notifications):
            line = recipient_line(item.recipient, f": {item.label}" + (f" — {item.state.detail}" if item.state.detail else ""))
            for reader in item.displayed_to:
                line += (Span(" · Read by ", MutedRole),
                         Span(reader.name, NameRole, OpenTarget(reader.name)))
            lines.append(line)
        return tuple(lines)


@dataclass(frozen=True)
class EmptyCheckedNotifications(CheckedNotifications):
    """The original matched, but no delivery receipts are visible to this viewer."""

    notifications: tuple[()] = field(default=(), init=False)
    queue_title = "No receipts"

    @property
    def details(self) -> DetailLines:
        return ((Span("No delivery info yet.", MutedRole),),)


@dataclass(frozen=True)
class UnavailableNotifications(NotificationStatus):
    error: str
    title = "Delivery status unavailable"

    @property
    def role(self) -> type[LineRole]:
        return NoticeRole

    @property
    def details(self) -> DetailLines:
        return ((Span(f"Couldn't check delivery status: {self.error}", MutedRole),),)
