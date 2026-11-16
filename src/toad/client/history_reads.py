"""Marking what a reader was actually shown as read: one acknowledgement at a time, started
only after a paint has shown the message text."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable
from dataclasses import dataclass

from agent_comms.storage.maintenance_barrier import MaintenanceHeldError


class PaintedRead(ABC):
    """What a view can start after its current rows have been painted."""

    @abstractmethod
    def start(self, marker: ReadMarking) -> object:
        """Start what the paint lets this view acknowledge; the frontend's handle to it, if any."""


class NothingToRead(PaintedRead):
    def start(self, marker: ReadMarking) -> None:
        pass


@dataclass(frozen=True)
class ReadWork(PaintedRead):
    work: Awaitable[None]

    async def run(self, marker: ReadMarking) -> None:
        try:
            await self.work
        except MaintenanceHeldError as error:
            # The refused evidence stays unread; a later paint supplies fresh work.
            marker.read_postponed(error)

    def start(self, marker: ReadMarking) -> object:
        return marker.start_read(self.run(marker))


class ReadMarking:
    """One painted-read operation at a time, for pagers and native/CLI sessions. The frontend
    owns the operation's native handle; a mixin beside a native node, so its hooks are declared
    without ABC's metaclass."""

    def mark_visible(self) -> None:
        if self.read_running():
            return
        self.read_visible().start(self)

    @abstractmethod
    def read_visible(self) -> PaintedRead:
        """What the rows painted now let this view acknowledge."""

    @abstractmethod
    def read_running(self) -> bool:
        """Whether this view's acknowledgement is still running."""

    @abstractmethod
    def start_read(self, work: Awaitable[None]) -> object:
        """Run this view's one acknowledgement on the frontend's loop; its native handle."""

    @abstractmethod
    def read_postponed(self, error: MaintenanceHeldError) -> None:
        """The bus was held for maintenance; the message stays unread."""
