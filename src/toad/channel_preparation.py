"""Typed channel sources and bounded reads, independent of native publication."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from functools import partial
from dataclasses import dataclass, replace
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.message_page import MessagePage
from agent_comms.presentation import WireRevision
from toad.conversation_kind import ConversationKind


@dataclass(frozen=True, eq=False)
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
    def matches_revision(self, revision: WireRevision) -> bool: ...

    @abstractmethod
    def read_changed(self, revision: WireRevision, high_water: int, follow_tail: bool) -> HistoryReadResult: ...

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

    def read(self, follow_tail: bool = True) -> HistoryReadResult:
        """Revision, scan watermark and page I/O share the original source."""
        return self.read_revision(self.comms.views.revision(), follow_tail)

    @abstractmethod
    def read_revision(self, revision: WireRevision, follow_tail: bool) -> HistoryReadResult: ...

    def changed(self, revision: WireRevision, follow_tail: bool) -> HistoryReadResult:
        return self.read_changed(revision, self.comms.bus.log.latest_sequence(), follow_tail)

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
            self.display_after(result),
        )


@dataclass(frozen=True, eq=False)
class InitialHistoryReadRequest(HistoryReadRequest):
    loading = True

    def matches_revision(self, revision: WireRevision) -> bool:
        return False

    def read_revision(self, revision: WireRevision, follow_tail: bool) -> HistoryReadResult:
        return self.changed(revision, follow_tail)

    def read_changed(self, revision: WireRevision, high_water: int, follow_tail: bool) -> HistoryReadResult:
        return HistoryReadResult(self, revision, high_water, self.page(limit=self.initial_limit), True, follow_tail)

    def consumed_sequence(self, result: HistoryReadResult, follow_tail: bool) -> int:
        return result.high_water

    def display_after(self, result: HistoryReadResult) -> tuple | None:
        assert result.page is not None
        return self.kind.display_identity(result.page)


@dataclass(frozen=True, eq=False)
class IncrementalHistoryReadRequest(HistoryReadRequest):
    after: int
    revision: WireRevision
    display_identity: tuple | None
    loading = False

    def matches_revision(self, revision: WireRevision) -> bool:
        return revision == self.revision

    def read_revision(self, revision: WireRevision, follow_tail: bool) -> HistoryReadResult:
        if self.matches_revision(revision):
            return HistoryReadResult(self, revision, self.after, None, False, follow_tail)
        return self.changed(revision, follow_tail)

    def read_changed(self, revision: WireRevision, high_water: int, follow_tail: bool) -> HistoryReadResult:
        if high_water <= self.after:
            if self.display_identity is not None and revision.stores_changed_since(self.revision):
                probe = self.page(limit=1)
                if self.kind.display_identity(probe) != self.display_identity:
                    return HistoryReadResult(self, revision, high_water,
                                             self.page(limit=self.initial_limit), True, follow_tail)
            return HistoryReadResult(self, revision, high_water, None, False, follow_tail)
        page = self.page(after=self.after, limit=self.page_limit)
        if self.display_identity is not None and self.kind.display_identity(page) != self.display_identity:
            return HistoryReadResult(self, revision, high_water,
                                     self.page(limit=self.initial_limit), True, follow_tail)
        replace_tail = bool(page.messages and page.has_newer and follow_tail)
        if replace_tail:
            page = self.page(limit=self.initial_limit)
        return HistoryReadResult(self, revision, high_water, page, replace_tail, follow_tail)

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
    follow_tail: bool


class PagesAhead:
    """Transport pages read beyond one edge of the mounted rows, nearest first.

    A Core page read costs about the same for four messages as for forty.
    The mounted history admits a few rows per frame, so the reader reads
    whole transport pages and hands them out in parts.
    """

    def __init__(self, older: bool, edge) -> None:
        self.older = older
        # The cursor the next part continues from, and the one the next read does.
        self.edge = self.far = edge
        self.more = True
        self.pages: deque[MessagePage] = deque()
        self.reading = asyncio.Lock()

    @property
    def count(self) -> int:
        return sum(len(page.messages) for page in self.pages)

    def bounds(self) -> dict:
        return {"before": self.far, "after": None} if self.older else {"before": None, "after": self.far}

    def add(self, page: MessagePage) -> None:
        self.pages.append(page)
        self.more = bool(page.messages) and (page.has_older if self.older else page.has_newer)
        if page.messages:
            self.far = page.oldest_cursor if self.older else page.newest_cursor

    def take(self, limit: int) -> MessagePage:
        """The next `limit` messages from the edge, as a page that says whether more follow."""
        page = self.pages[0]
        if len(page.messages) <= limit:
            part = self.pages.popleft()
        elif self.older:
            part = replace(page, messages=page.messages[-limit:], has_older=True)
            self.pages[0] = replace(page, messages=page.messages[:-limit], has_newer=True)
        else:
            part = replace(page, messages=page.messages[:limit], has_newer=True)
            self.pages[0] = replace(page, messages=page.messages[limit:], has_older=True)
        if part.messages:
            self.edge = part.oldest_cursor if self.older else part.newest_cursor
        return part


class ChannelHistoryReader:
    """Own one logical source and its reads until their actual I/O completes."""

    def __init__(self, source: HistoryReadRequest) -> None:
        self.source = source
        self._ahead: dict[bool, PagesAhead] = {}
        self._pending: set[asyncio.Task[HistoryReadResult] | asyncio.Task[MessagePage] | asyncio.Task[bool]] = set()
        self._closed = False

    @property
    def comms(self) -> Comms:
        return self.source.comms

    def current(self, result: HistoryReadResult, follow_tail: bool) -> bool:
        return result.request is self.source and result.follow_tail == follow_tail

    def accept(self, result: HistoryReadResult, follow_tail: bool) -> None:
        self.source = result.request.advance(result, follow_tail)
        # The accepted read may have added messages after the newest page held.
        # Older pages stay as valid as the rows already mounted from this source.
        self._ahead.pop(False, None)

    def restart(self) -> None:
        self.source = self.source.restart()
        self._ahead.clear()

    async def read(self, follow_tail: bool) -> HistoryReadResult:
        return await self._run(partial(self.source.read, follow_tail))

    async def page(self, *, before: int | None = None, after: int | None = None,
                   limit: int) -> MessagePage:
        """Up to `limit` messages next to one edge of the mounted rows."""
        older = before is not None
        ahead = await self._read_ahead(older, before if older else after, 1, lambda: True)
        return ahead.take(limit)

    async def read_ahead(self, older: bool, edge, count: int, current: Callable[[], bool]) -> None:
        """Hold `count` messages beyond `edge` while the request stays current."""
        if current():
            await self._read_ahead(older, edge, count, current)

    async def _read_ahead(self, older: bool, edge, count: int, current: Callable[[], bool]) -> PagesAhead:
        ahead = self._ahead.get(older)
        if ahead is None or ahead.edge != edge or not (ahead.pages or ahead.more):
            ahead = self._ahead[older] = PagesAhead(older, edge)
        source = self.source
        while ahead.count < count and ahead.more and current():
            async with ahead.reading:
                # The read this one waited for may have brought enough.
                if ahead.count < count and ahead.more:
                    ahead.add(await self._run(partial(source.page, **ahead.bounds(), limit=source.page_limit)))
        return ahead

    async def route_current(self) -> bool:
        """Read the route on this reader's joined I/O lifetime."""
        from agent_comms.route_selection import root_is_current

        return await self._run(partial(root_is_current, self.comms.root))

    async def _run[T](self, read: Callable[[], T]) -> T:
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
