"""What is known about a message's notifications, as text any frontend can show."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.presentation import MessageNotification


class NotificationStatus(ABC):
    """One state of the check: its one-line title and the details behind it."""

    working: ClassVar[bool] = False
    unavailable: ClassVar[bool] = False

    @property
    @abstractmethod
    def title(self) -> str: ...

    @property
    @abstractmethod
    def details(self) -> str: ...


@dataclass(frozen=True)
class UncheckedNotifications(NotificationStatus):
    title = "Notification status not checked"
    details = "Not checked yet"


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
    def details(self) -> str:
        return "\n".join(
            f"{item.recipient}: {item.state}" + (f" — {item.detail}" if item.detail else "")
            for item in self.ordered
        ) or "No notification result is recorded for this message. This does not confirm the message was received."


@dataclass(frozen=True)
class UnavailableNotifications(NotificationStatus):
    error: str
    unavailable = True
    title = "Notification status unavailable"

    @property
    def details(self) -> str:
        return f"Could not check notification status: {self.error}"
