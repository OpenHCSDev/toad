"""What is known about a message's notifications: the one-line title and the details behind it."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import ClassVar, TYPE_CHECKING

from agent_comms.message_reference import MessageReference
from agent_comms.presentation import MessageNotification
from toad.line_blocks import LineBlock, MutedRole, NameRole, NoticeRole, OpenTarget, Span, SpanColumns, WorkingRole

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
    def details(self) -> DetailLines:
        return ()

    @property
    def disclosure(self) -> SpanColumns:
        return SpanColumns(self.details, indent=2)

    def blocks(self, shown: Shown) -> tuple[LineBlock, ...]:
        """The feedback row and its disclosure, shared by every message fragment."""
        role = NoticeRole if self.unavailable else WorkingRole if self.working else MutedRole
        summary = shown.summary(self.title, role)
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
            yield cls(tuple(item for reference in loaded for item in results[reference]))

    @property
    def working(self) -> bool:
        return any(item.state.working for item in self.notifications)

    @property
    def title(self) -> str:
        return MessageNotification.summary(self.notifications)

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
            (Span("No notification result is recorded for this message. "
                  "This does not confirm the message was received.", MutedRole),),))


@dataclass(frozen=True)
class UnavailableNotifications(NotificationStatus):
    error: str
    unavailable = True
    title = "Notification status unavailable"

    @property
    def details(self) -> DetailLines:
        return ((Span(f"Could not check notification status: {self.error}", MutedRole),),)
