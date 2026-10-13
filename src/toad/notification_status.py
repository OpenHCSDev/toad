"""What is known about a message's notifications: the one-line title and the details behind it."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.presentation import MessageNotification
from toad.line_blocks import MutedRole, NameRole, OpenTarget, Span


DetailLines = tuple[tuple[Span, ...], ...]
"""The details behind one notification state: lines of line-block spans."""


def recipient_line(recipient: str, text: str) -> tuple[Span, ...]:
    """One feedback line whose agent name opens that agent's thread.

    The name is a thread name like every drawn thread name: a ``NameRole`` span
    carrying the one link owner all of them use (``OpenTarget``, opened by
    ``OpensLinks``).
    """
    return (Span(recipient, NameRole, OpenTarget(recipient)), Span(text, MutedRole))


class NotificationStatus(ABC):
    """One state of the check: its one-line title and the details behind it."""

    working: ClassVar[bool] = False
    unavailable: ClassVar[bool] = False

    @property
    @abstractmethod
    def title(self) -> str: ...

    @property
    @abstractmethod
    def details(self) -> DetailLines: ...


@dataclass(frozen=True)
class UncheckedNotifications(NotificationStatus):
    title = "Notification status not checked"

    @property
    def details(self) -> DetailLines:
        return ((Span("Not checked yet", MutedRole),),)


@dataclass(frozen=True)
class CheckedNotifications(NotificationStatus):
    notifications: tuple[MessageNotification, ...]

    @property
    def ordered(self) -> list[MessageNotification]:
        return sorted(self.notifications, key=lambda item: (item.priority, item.recipient.casefold()))

    @property
    def working(self) -> bool:
        return any(item.busy for item in self.notifications)

    @property
    def title(self) -> str:
        counts = Counter(item.state for item in self.ordered)
        states = list(counts)
        summary = " · ".join(f"{state} ({counts[state]})" for state in states[:3])
        if len(states) > 3:
            summary += f" · {sum(counts[state] for state in states[3:])} others"
        return summary or "No recorded notification result"

    @property
    def details(self) -> DetailLines:
        lines = [recipient_line(item.recipient, f": {item.state}" + (f" — {item.detail}" if item.detail else ""))
                 for item in self.ordered]
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
