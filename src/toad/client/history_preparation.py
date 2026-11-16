"""Page ends: traversal, source reads and eviction at the older and newer edge of a transcript
history, and the page requests and revisions they key. Native placement stays on the history and
window passed in."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import ClassVar

from agent_comms.execution.transcript_sources import TranscriptCursor
from agent_comms.messaging.message_page import MessagePage, PageBounds
from agent_comms.transcript.transcripts import TranscriptPage
from agent_comms.ui_model.message_category import MessageCategory

from toad.work_preparation import WorkRevision


class PageEnd(ABC):
    """One end owns page traversal, source reads and eviction at that edge."""

    step: ClassVar[int]
    accepts_destination = True

    def boundary(self, page) -> int:
        return self.entry(len(page.fragments) + 1)

    def indices(self, page, boundary: int) -> range:
        return range(boundary + min(self.step, 0), self.edge((-1, len(page.fragments))), self.step)

    def can_extend(self, page) -> bool:
        return self.edge((page.start, len(page.fragments) - page.stop)) > 0

    def has_more(self, through, page) -> bool:
        return self.edge((page.has_older, page.has_newer))

    def adjacent(self, page) -> PageRequest:
        return PageRequest(self, self.edge((page.before, page.after)))
    @abstractmethod
    def advance_empty(self, edge, staged) -> None: ...
    @abstractmethod
    def edge[Item](self, pages: Sequence[Item]) -> Item: ...
    def edge_boundary(self, edge, local: bool, staged) -> int:
        return self.edge((edge.prepared.start, edge.prepared.stop)) if local else self.boundary(staged)
    @abstractmethod
    async def mount(self, history, view, pages: deque) -> None: ...
    @staticmethod
    @abstractmethod
    def append[Item](pages: deque[Item], view: Item, /) -> None: ...
    @staticmethod
    @abstractmethod
    def pop[Item](pages: deque[Item], /) -> Item: ...

    def eviction_fragments(self, page):
        return page.fragments_in_range[:: -self.step]
    def rows_toward(self, runway) -> int:
        return self.edge((runway.above, runway.below))
    def at_boundary(self, window) -> bool:
        boundary = self.edge((0, window.max_scroll_y))
        return all((position - boundary) * self.step >= 0
                   for position in (window.scroll_y, window.scroll_target_y))

    @abstractmethod
    def work_revision[Cursor](self, request: PageRequest[Cursor], through: Cursor) -> WorkRevision: ...
    @abstractmethod
    async def load_page(self, loader, cursor: TranscriptCursor, through) -> TranscriptPage: ...
    def progressed(self, page: TranscriptPage, cursor: TranscriptCursor) -> bool:
        edge = self.edge((page.before, page.after))
        start, stop = self.edge(((edge, cursor), (cursor, edge)))
        return cursor.accepts_source(edge) and not (
            start.contains(stop) and self.edge((page.has_older, page.has_newer)))
    @abstractmethod
    def wire_page(self, source, cursor, through) -> MessagePage: ...

    def entry(self, length: int):
        return self.edge((length - 1, 0))

    async def project(
        self, source, initial, prepared,
    ):
        return replace(prepared, page=replace(prepared.page, has_newer=True))

    def visible_more(self, history):
        return history.has_more(self)

    def fresh(self, history) -> bool:
        return False

    def accepts_velocity(self, velocity: float) -> bool:
        return velocity * self.step > 0

    async def walk(
        self, history, current: Callable[[], bool], target,
        selected: frozenset[type[MessageCategory]], start: tuple[int, int], rows_needed: int, limit: int,
    ):
        for index in range(start[0], self.edge((-1, len(history.pages))), self.step):
            if not current() or rows_needed <= 0 or limit <= 0:
                break
            page = history.pages[index].prepared
            boundary = start[1] if index == start[0] else self.boundary(page)
            rows_needed -= await page.prepare_rows(
                history, current, target=target, selected=selected, end=self,
                boundary=boundary, rows_needed=rows_needed, limit=limit)
            limit -= page.stop - page.start
        return rows_needed, limit

    def eviction_order(self, history) -> tuple[PageEnd, PageEnd]:
        return OLDER_END, NEWER_END

    def can_evict(self, overlay_visible: bool) -> bool:
        return True

    def leave_tail(self, window) -> None:
        pass

    def trim(self, view, count: int) -> None:
        page = view.prepared
        page.set_fragment_range(slice(page.start + self.edge((count, 0)), page.stop - self.edge((0, count))))
        view.range_changed()


class OlderEnd(PageEnd):
    def work_revision[Cursor](self, request: PageRequest[Cursor], through: Cursor) -> WorkRevision:
        return PageRevision(request)

    step = -1
    pop = staticmethod(deque.popleft)
    append = staticmethod(deque.appendleft)

    async def load_page(self, loader, cursor, through) -> TranscriptPage:
        return await through.read_page(loader, cursor.earlier_page())

    def wire_page(self, source, cursor, through) -> MessagePage:
        return source.conversation.page(source, PageBounds(
            cursor.older(),
            source.tail_limit if cursor == through else source.page_limit))

    def advance_empty(self, edge, staged) -> None:
        edge.page = replace(edge.page, before=staged.page.before, has_older=staged.page.has_older)

    def edge[Item](self, pages: Sequence[Item]) -> Item:
        return pages[0]

    async def mount(self, history, view, pages: deque) -> None:
        await history.mount(view, before=self.edge(pages) if pages else history.newer)

    def eviction_order(self, history) -> tuple[PageEnd, PageEnd]:
        return super().eviction_order(history) if history.follows_source_tail else (NEWER_END, self)

    def can_evict(self, overlay_visible: bool) -> bool:
        return not overlay_visible

    def leave_tail(self, window) -> None:
        window.release_anchor()


class NewerEnd(PageEnd):
    def work_revision[Cursor](self, request: PageRequest[Cursor], through: Cursor) -> WorkRevision:
        return GrowingPageRevision(request, through)

    step = 1
    accepts_destination = False
    pop = staticmethod(deque.pop)
    append = staticmethod(deque.append)

    def has_more(self, through, page):
        return super().has_more(through, page) or page.after != through

    async def load_page(self, loader, cursor, through) -> TranscriptPage:
        return await through.read_page(loader, cursor.later_page())

    def wire_page(self, source, cursor, through) -> MessagePage:
        page = source.conversation.page(source, PageBounds(cursor.newer(), source.page_limit))
        kept = tuple(message for message in page.messages if message.view_key[0] or message.seq <= through.cursor.sequence)
        return replace(page, messages=kept, has_newer=False) if len(kept) < len(page.messages) else page

    async def project(
        self, source, initial, prepared,
    ):
        if not prepared.fragments and not prepared.page.has_newer:
            boundary = await source.boundary()
            return replace(boundary, page=replace(boundary.page, before=initial.page.before,
                                                 has_older=initial.page.has_older))
        return await super().project(source, initial, prepared)

    def advance_empty(self, edge, staged) -> None:
        edge.page = replace(edge.page, after=staged.page.after, has_newer=staged.page.has_newer)

    def fresh(self, history):
        return history.drawn_tail_followed

    def edge[Item](self, pages: Sequence[Item]) -> Item:
        return pages[-1]

    async def mount(self, history, view, pages: deque) -> None:
        await history.mount(view, before=history.newer)


OLDER_END = OlderEnd()


NEWER_END = NewerEnd()


@dataclass(frozen=True)
class PageRequest[Cursor = TranscriptCursor]:
    end: PageEnd
    cursor: Cursor

    def progressed(self: PageRequest[TranscriptCursor], page: TranscriptPage) -> bool:
        return self.end.progressed(page, self.cursor)


@dataclass(frozen=True)
class PageRevision[Cursor = TranscriptCursor](WorkRevision):
    """An older request is bounded by its own cursor, independent of new arrivals."""

    request: PageRequest[Cursor]
    size: ClassVar[int] = 512


@dataclass(frozen=True)
class GrowingPageRevision[Cursor = TranscriptCursor](PageRevision[Cursor]):
    """A newer request also depends on the frontier this read reached."""

    through: Cursor
