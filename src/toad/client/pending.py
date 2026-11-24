"""What the reader sees while the UI waits: one owner for every wait, in both frontends.

A wait is declared once, as a `PendingWork` member with the words the reader sees. A surface
that shows waits (`ShowsPending`) is told when one starts and ends; it shows the work only
after `pending_delay`, so a wait shorter than that never flashes, and it always clears when
the work finishes, fails or is cancelled. An operation kind that the reader waits on is tied
to its work with `awaited`, so a host that runs operations shows the work for any of them
without a spinner at its call site.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import ClassVar, TypeVar


class PendingWork:
    """Work the reader is waiting on, and the words that say so."""

    label: ClassVar[str]

    _operations: ClassVar[dict[type, type[PendingWork]]] = {}

    @classmethod
    def for_operation(cls, kind: type) -> type[PendingWork]:
        """The work an operation kind makes the reader wait on; none for background work."""
        return PendingWork._operations.get(kind, NoPendingWork)

    @classmethod
    async def await_on[T](cls, surface: ShowsPending, awaitable: Awaitable[T]) -> T:
        """Await ``awaitable`` on ``surface``, showing this work after ``pending_delay``."""
        shown = asyncio.get_running_loop().call_later(surface.pending_delay, surface.show_pending, cls)
        try:
            return await awaitable
        finally:
            shown.cancel()
            surface.clear_pending(cls)


class NoPendingWork(PendingWork):
    """Background work: nothing is shown while it runs."""

    label = ""

    @classmethod
    async def await_on[T](cls, surface: ShowsPending, awaitable: Awaitable[T]) -> T:
        return await awaitable


class ThreadOpening(PendingWork):
    """A thread's tab while its thread and saved history are read."""

    label = "Loading thread and history…"


class HistoryPage(PendingWork):
    """A conversation's first page of messages."""

    label = "Loading messages…"


class ChoicesPreparation(PendingWork):
    """A command form's choices while the catalog is read."""

    label = "Loading choices…"


class BusConnecting(PendingWork):
    """A bus switch while the new bus is reached and observed."""

    label = "Connecting to the bus…"


class ActionRunning(PendingWork):
    """A chosen action that reads or writes Core before anything changes on screen."""

    label = "Working…"


class Applying(PendingWork):
    """A submitted form while Core applies it."""

    label = "Applying…"


Kind = TypeVar("Kind", bound=type)


def awaited(work: type[PendingWork]) -> Callable[[Kind], Kind]:
    """Declare that the reader waits on operations of the decorated kind as `work`."""

    def declare(kind: Kind) -> Kind:
        PendingWork._operations[kind] = work
        return kind

    return declare


class ShowsPending(ABC):
    """A surface that shows the work the reader is waiting on.

    `while_pending` is the one algorithm: show the work after `pending_delay` unless it has
    finished, then clear it however it ends. Each frontend says how it shows and clears."""

    pending_delay: ClassVar[float] = 0.15

    @abstractmethod
    def show_pending(self, work: type[PendingWork]) -> None:
        """Show that the reader is waiting on `work`."""

    @abstractmethod
    def clear_pending(self, work: type[PendingWork]) -> None:
        """`work` has ended; stop showing it."""

    async def while_pending[T](self, work: type[PendingWork], awaitable: Awaitable[T]) -> T:
        """Await `awaitable`, showing `work` once it has taken longer than `pending_delay`."""
        return await work.await_on(self, awaitable)


class AwaitsFirstPage:
    """A conversation history the reader waits on until its first page is drawn.

    The reader is told `first_page` from the start; when rows are published and something
    of the source is drawn, the frontend puts the wait away. Mixed in before the shared
    pager, whose `rows_published` it extends, on a history that answers `undrawn`. A plain
    class, not an ABC: Textual's histories are widgets with Textual's own metaclass."""

    first_page: ClassVar[type[PendingWork]] = HistoryPage

    def first_page_drawn(self) -> None:
        """Something of the source is drawn: stop showing `first_page`."""
        raise NotImplementedError

    def rows_published(self) -> None:
        super().rows_published()  # type: ignore[misc]
        if not self.undrawn:  # type: ignore[attr-defined]
            self.first_page_drawn()
