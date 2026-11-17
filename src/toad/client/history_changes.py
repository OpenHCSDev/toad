"""The data a history window carries about its top row and its open change.

Both backends read a `TopPage` to find the reader, a `PinnedHeader` to draw the sticky
header over the top row, and open a `HistoryChange` to batch the layouts around a row
shift. The classes stay toolkit-neutral; the window they reference supplies its own
toolkit's refresh and attach checks.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from toad.client.reader_position import (
    BlockPosition,
    FragmentPosition,
    ReaderPosition,
)


if TYPE_CHECKING:
    from toad.client.line_blocks import Divider
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_history import FragmentSpan, TranscriptPageView


class TopPage:
    """No drawn page reaches the window's top row or below it: live blocks hold the reader."""

    def reader_position(self, window: HistoryWindow) -> ReaderPosition:
        return BlockPosition.of(window)

    def pinned_header(self, window: HistoryWindow) -> PinnedHeader:
        return window.live_message_header()


@dataclass(frozen=True)
class PageBelowTop(TopPage):
    """The nearest drawn page starts below the top row: the reader is on its first row."""

    page: TranscriptPageView
    first: int

    def span(self, window: HistoryWindow) -> FragmentSpan:
        """The measured child drawn on the top row, or the page's first one."""
        return self.page.fragment_at(max(0, int(window.scroll_y - self.first))).location()

    def reader_position(self, window: HistoryWindow) -> ReaderPosition:
        span = self.span(window)
        return FragmentPosition(span.fragment.key, (window.scroll_y - self.first - span.first) / span.height,
                                span.height, block=span.index)


@dataclass(frozen=True)
class PageUnderTop(PageBelowTop):
    """A drawn page holds the top row; its message pins its header in the flow's own column."""

    def pinned_header(self, window: HistoryWindow) -> PinnedHeader:
        span = self.span(window)
        row = int(window.scroll_y - self.first)
        return PinnedHeader(span.fragment.sticky_header(span.index, row - span.first),
                            self.page.content_region.x - window.content_region.x, self.page.size.width)


@dataclass(frozen=True)
class PinnedHeader:
    """The header to pin over a window's top row and the column its message draws it in (x from
    the window's content edge, and width), so the pinned copy sits and wraps exactly as the
    flow's own header does."""

    headers: tuple[Divider, ...]
    x: int
    width: int


class NoHistoryChange:
    """No change is open: the reader's own movement is read from the viewport, and a change opens fresh."""

    layout_requests = 0

    def moved(self, position: ReaderPosition, window: HistoryWindow, rows: float) -> ReaderPosition:
        return ReaderPosition.of(window)

    def check_follow(self, window: HistoryWindow) -> bool:
        """Keep a following reader on the tail; True when that scrolled the window."""
        if not window.follows_tail:
            return False
        previous = window.scroll_y
        with window.layout_scroll():
            window.scroll_y = window.tail_scroll_y
        return previous != window.scroll_y

    def finish_layout(self, answered: int) -> None:
        """No change waits on a layout."""

    def release(self) -> None:
        """No change waits on a layout."""

    @asynccontextmanager
    async def opened(self, window: HistoryWindow):
        """One change and the layout that shows it.

        A body worker owns its own tree change and a nested pager may take
        history_lock while building that body, so this scope holds neither
        lock while it waits.
        """
        screen = window.screen
        window.keep_reader()
        change = window.history_change = HistoryChange()
        geometry = window._geometry_revision
        drawn = False
        try:
            try:
                yield
            finally:
                # An unchanged page or already-live body needs no other layout.
                if window._geometry_revision != geometry:
                    change.request_layout(window)
            if window._geometry_revision == geometry:
                # No row moved: a position kept for this change is where the reader is.
                drawn = True
                return
            # Without waiting for the layout that places the reader, the next
            # change would start from rows that are not laid out yet.
            if window.is_attached and screen.is_current:
                await change.wait()
                drawn = change.laid_out
        finally:
            if window.history_change is change:
                window.history_change = NO_HISTORY_CHANGE
                # The change is drawn, so the position has done its work and
                # the next change reads where the reader is then. One that no
                # layout has placed yet (a covered screen) stays kept.
                if drawn:
                    window.place_reader()


NO_HISTORY_CHANGE = NoHistoryChange()


@dataclass(eq=False)
class HistoryChange:
    """One change to what a history window draws, and the layout that shows it."""

    layout_ready: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    layout_requests: int = field(default=0, init=False)
    """How many layouts this change has requested; a layout answers those made before it started."""
    laid_out: bool = field(default=False, init=False)
    """Whether a layout has shown this change's final rows (and put the reader on the kept position)."""

    def request_layout(self, window: HistoryWindow) -> None:
        # Layouts during the change do not show its final rows.
        # Arm the event before making that layout actionable.
        self.layout_requests += 1
        self.laid_out = False
        self.layout_ready.clear()
        window.refresh(layout=True)

    def finish_layout(self, answered: int) -> None:
        """A layout that started after `answered` requests has finished.

        A layout running over loop turns may finish after a request made while
        it ran; that request waits for the layout that places it.
        """
        if answered == self.layout_requests:
            self.laid_out = True
            self.layout_ready.set()

    def release(self) -> None:
        """No layout will answer: release the waiter."""
        self.layout_ready.set()

    async def wait(self) -> None:
        await self.layout_ready.wait()

    def moved(self, position: ReaderPosition, window: HistoryWindow, rows: float) -> ReaderPosition:
        """The kept message moves with the reader while the change is open."""
        return position.shifted(rows)

    def check_follow(self, window: HistoryWindow) -> bool:
        """The change's own layout places a following reader."""
        return False

    @asynccontextmanager
    async def opened(self, window: HistoryWindow):
        """A change inside another joins it."""
        yield
