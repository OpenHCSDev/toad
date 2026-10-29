"""What is known about a message's notifications: the one-line title and the details behind it."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import ClassVar, TYPE_CHECKING

from agent_comms.message_reference import MessageReference
from agent_comms.presentation import MessageNotification
from toad.line_blocks import LineBlock, LineLink, MutedRole, NameRole, NoticeRole, OpenTarget, Span, SpanColumns, WorkingRole

if TYPE_CHECKING:
    from toad.widgets.transcript_fragments import Shown


DetailLines = tuple[tuple[Span, ...], ...]
"""The details behind one notification state: lines of line-block spans."""


def recipient_line(recipient: str, text: str) -> tuple[Span, ...]:
    """One feedback line whose agent name opens that agent's thread.

    The name is a thread name like every drawn thread name: a ``NameRole`` span
    carrying the one link owner all of them use (``OpenTarget``, opened by
    ``OpensLinks``).
    """
    return (Span(recipient, NameRole, OpenTarget(recipient)), Span(text, MutedRole))


class NotificationStatus:
    """One state of the check: its one-line title and the details behind it."""

    working: ClassVar[bool] = False
    unavailable: ClassVar[bool] = False

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
    def disclosure(self) -> SpanColumns:
        return SpanColumns(self.details, indent=2)

    def blocks(self, shown: Shown, link: LineLink) -> tuple[LineBlock, ...]:
        """The feedback row and its disclosure, shared by every message fragment."""
        role = NoticeRole if self.unavailable else WorkingRole if self.working else MutedRole
        summary = shown.summary(self.title, role, link)
        return ((summary, self.disclosure)
                if shown.details_open else (summary,))


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

    @property
    def working(self) -> bool:
        return any(item.state.working for item in self.notifications)

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
            *((Span(f"Recipient {item.recipient_identity.recipient_lookup}", MutedRole),)
              for item in leading.notifications),
            *leading.details,
            *((Span(f"Answer {item.answer.seq}/{item.answer.message_id}", MutedRole),)
              for item in leading.notifications if item.answer is not None),
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
        return (tuple(lines) if lines else (
            (Span("No recipient feedback to display.", MutedRole),),))


@dataclass(frozen=True)
class EmptyCheckedNotifications(CheckedNotifications):
    """The original matched, but no recipient feedback is visible to this viewer."""

    notifications: tuple[()] = field(default=(), init=False)
    queue_title = "No recipient feedback"


@dataclass(frozen=True)
class UnavailableNotifications(NotificationStatus):
    error: str
    unavailable = True
    title = "Notification status unavailable"

    @property
    def details(self) -> DetailLines:
        return ((Span(f"Could not check notification status: {self.error}", MutedRole),),)
