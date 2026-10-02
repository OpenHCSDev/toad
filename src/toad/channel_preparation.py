"""Typed channel sources and bounded reads, independent of native publication."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import partial
from dataclasses import dataclass, replace
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.message_page import MessagePage
from agent_comms.presentation import WireRevision
from toad.conversation_kind import ConversationKind


@dataclass(frozen=True)
class HistoryReadRequest(ABC):
    comms: Comms
    kind: type[ConversationKind]
    target: str
    project: Path
    initial_limit: int
    page_limit: int
    max_bytes: int

    @property
    @abstractmethod
    def loading(self) -> bool: ...

    @abstractmethod
    def for_view(self, follow_tail: bool) -> HistoryReadRequest: ...

    @abstractmethod
    def matches_revision(self, revision: WireRevision) -> bool: ...

    @abstractmethod
    def read_changed(self, revision: WireRevision, high_water: int) -> HistoryReadResult: ...

    @abstractmethod
    def consumed_sequence(self, result: HistoryReadResult, follow_tail: bool) -> int: ...

    @abstractmethod
    def display_after(self, result: HistoryReadResult) -> tuple | None: ...

    def page(self, *, before: int | None = None, after: int | None = None,
             limit: int) -> MessagePage:
        return self.kind.page(
            self.comms, self.target, worktree=str(self.project),
            before=before, after=after, limit=limit, max_bytes=self.max_bytes,
        )

    def read(self) -> HistoryReadResult:
        """Revision, scan watermark and page I/O share the original source."""
        return self.read_revision(self.comms.views.revision())

    @abstractmethod
    def read_revision(self, revision: WireRevision) -> HistoryReadResult: ...

    def changed(self, revision: WireRevision) -> HistoryReadResult:
        return self.read_changed(revision, self.comms.bus.log.latest_sequence())

    def restart(self) -> InitialHistoryReadRequest:
        return InitialHistoryReadRequest(
            self.comms, self.kind, self.target, self.project,
            self.initial_limit, self.page_limit, self.max_bytes,
        )

    def advance(self, result: HistoryReadResult, follow_tail: bool) -> IncrementalHistoryReadRequest:
        return IncrementalHistoryReadRequest(
            self.comms, self.kind, self.target, self.project,
            self.initial_limit, self.page_limit, self.max_bytes,
            self.consumed_sequence(result, follow_tail), result.revision,
            self.display_after(result), follow_tail,
        )


@dataclass(frozen=True)
class InitialHistoryReadRequest(HistoryReadRequest):
    loading = True

    def for_view(self, follow_tail: bool) -> HistoryReadRequest:
        return self

    def matches_revision(self, revision: WireRevision) -> bool:
        return False

    def read_revision(self, revision: WireRevision) -> HistoryReadResult:
        return self.changed(revision)

    def read_changed(self, revision: WireRevision, high_water: int) -> HistoryReadResult:
        return HistoryReadResult(self, revision, high_water, self.page(limit=self.initial_limit), True)

    def consumed_sequence(self, result: HistoryReadResult, follow_tail: bool) -> int:
        return result.high_water

    def display_after(self, result: HistoryReadResult) -> tuple | None:
        assert result.page is not None
        return self.kind.display_identity(result.page)


@dataclass(frozen=True)
class IncrementalHistoryReadRequest(HistoryReadRequest):
    after: int
    revision: WireRevision
    display_identity: tuple | None
    follow_tail: bool
    loading = False

    def for_view(self, follow_tail: bool) -> HistoryReadRequest:
        return replace(self, follow_tail=follow_tail)

    def matches_revision(self, revision: WireRevision) -> bool:
        return revision == self.revision

    def read_revision(self, revision: WireRevision) -> HistoryReadResult:
        if self.matches_revision(revision):
            return HistoryReadResult(self, revision, self.after, None, False)
        return self.changed(revision)

    def read_changed(self, revision: WireRevision, high_water: int) -> HistoryReadResult:
        if high_water <= self.after:
            if self.display_identity is not None and revision.files != self.revision.files:
                probe = self.page(limit=1)
                if self.kind.display_identity(probe) != self.display_identity:
                    return HistoryReadResult(self, revision, high_water,
                                             self.page(limit=self.initial_limit), True)
            return HistoryReadResult(self, revision, high_water, None, False)
        page = self.page(after=self.after, limit=self.page_limit)
        if self.display_identity is not None and self.kind.display_identity(page) != self.display_identity:
            return HistoryReadResult(self, revision, high_water,
                                     self.page(limit=self.initial_limit), True)
        replace_tail = bool(page.messages and page.has_newer and self.follow_tail)
        if replace_tail:
            page = self.page(limit=self.initial_limit)
        return HistoryReadResult(self, revision, high_water, page, replace_tail)

    def consumed_sequence(self, result: HistoryReadResult, follow_tail: bool) -> int:
        page = result.page
        if page is None:
            return self.after
        if (result.replace_tail or follow_tail) and page.has_newer:
            return page.newest_seq or result.high_water
        return result.high_water

    def display_after(self, result: HistoryReadResult) -> tuple | None:
        return self.display_identity if result.page is None else self.kind.display_identity(result.page)


@dataclass(frozen=True)
class HistoryReadResult:
    request: HistoryReadRequest
    revision: WireRevision
    high_water: int
    page: MessagePage | None
    replace_tail: bool


class ChannelHistoryReader:
    """Own one logical source and its reads until their actual I/O completes."""

    def __init__(self, source: HistoryReadRequest) -> None:
        self.source = source
        self._pending: set[asyncio.Task[HistoryReadResult] | asyncio.Task[MessagePage]] = set()
        self._closed = False

    @property
    def comms(self) -> Comms:
        return self.source.comms

    def request(self, follow_tail: bool) -> HistoryReadRequest:
        return self.source.for_view(follow_tail)

    def accept(self, result: HistoryReadResult, follow_tail: bool) -> None:
        self.source = result.request.advance(result, follow_tail)

    def restart(self) -> None:
        self.source = self.source.restart()

    async def read(self, request: HistoryReadRequest) -> HistoryReadResult:
        return await self._run(request.read)

    async def page(self, *, before: int | None = None, after: int | None = None,
                   limit: int) -> MessagePage:
        return await self._run(partial(self.source.page, before=before, after=after, limit=limit))

    async def _run[T: (HistoryReadResult, MessagePage)](self, read: Callable[[], T]) -> T:
        if self._closed:
            raise RuntimeError("Channel history reader is closed")
        task = asyncio.create_task(asyncio.to_thread(read), name="channel-history-read")
        self._pending.add(task)

        def finished(completed: asyncio.Task[T]) -> None:
            self._pending.discard(completed)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
        await asyncio.wait((task,))
        return task.result()

    async def aclose(self) -> None:
        self._closed = True
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
