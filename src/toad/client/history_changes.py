"""The data a history window carries about its top row and its open change.

Both backends read a `TopPage` to find the reader, a `PinnedHeader` to draw the sticky
header over the top row, and open a `HistoryChange` to batch the layouts around a row
shift. The classes stay toolkit-neutral; the window they reference supplies its own
toolkit's refresh and attach checks.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from toad.client.reader_position import (
    BlockPosition,
    FragmentPosition,
    ReaderPosition,
)


from toad.client.line_blocks import Divider, MutedRole

if TYPE_CHECKING:
    from toad.client.fragments import FragmentKey, HistoryFragment
    from toad.client.transcript_fragments import TranscriptFragment
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
        return FragmentRowUnderTop(span.fragment, span.index, row - span.first,
                                   self.page.content_region.x - window.content_region.x,
                                   self.page.size.width).pinned_header()


@dataclass(frozen=True)
class FragmentRowUnderTop:
    """Row `row` of block `block` of `fragment` is on a window's top row, and the fragment is
    drawn in the column at `x` (from the window's content edge) `width` wide. Every frontend
    measures this in its own unit; the fragment alone decides which header that pins."""

    fragment: TranscriptFragment
    block: int
    row: int
    x: int
    width: int

    def pinned_header(self) -> PinnedHeader:
        return PinnedHeader(self.fragment.sticky_header(self.block, self.row), self.x, self.width)


@dataclass(frozen=True)
class PinnedHeader:
    """The header to pin over a window's top row and the column its message draws it in (x from
    the window's content edge, and width), so the pinned copy sits and wraps exactly as the
    flow's own header does."""

    headers: tuple[Divider, ...]
    x: int
    width: int


@dataclass(frozen=True)
class BurstMessage:
    """One message of an arrival burst: where it is drawn (`key`, its first arriving part) and
    the header its flow draws, which the pin draws again."""

    key: FragmentKey
    header: Divider


@dataclass(frozen=True)
class StackedHeaders:
    """The burst's headers a pin stacks above the top row's own: a count line, then each
    earlier message of the burst whose head the reader has scrolled past. `keys[i]` is the
    message `headers[i]` opens; the count line opens the earliest one."""

    headers: tuple[Divider, ...] = ()
    keys: tuple[FragmentKey, ...] = ()


NO_STACK = StackedHeaders()


@dataclass(frozen=True)
class ArrivalBurst:
    """Messages that arrived together at the end a reader follows (Tristan, 2026-11-18: "show
    the headers for all of them, like stacked, and then ... show the most recent one. So it'd
    be like, three came in, here's the latest").

    Arrivals whose publications come within `gap` seconds of each other are one burst; one
    after the gap starts the next. The window shows the latest as it shows any arrival, and its
    pin stacks the headers of the others the reader has scrolled past (`stack`). Nothing is
    collapsed or copied: the pin draws the messages' own header blocks. The burst ends when
    the reader scrolls up by hand or opens a stacked header (`PinsMessageHeader`)."""

    messages: tuple[BurstMessage, ...] = ()
    last: float = float("-inf")
    gap: ClassVar[float] = 4.0
    shown: ClassVar[int] = 3
    """The most earlier headers stacked; the count line says how many came."""

    def live(self, now: float) -> bool:
        return bool(self.messages) and now - self.last <= self.gap

    def arrived(self, fragments: tuple[HistoryFragment, ...], now: float) -> ArrivalBurst:
        """`fragments` arrived at the followed end: each message among them with a header
        joins this burst, or starts the next one after the gap."""
        kept = self.messages if self.live(now) else ()
        seen = {message.key.source for message in kept}
        joined = []
        for fragment in fragments:
            if fragment.pinned_dividers and fragment.source_identity not in seen:
                seen.add(fragment.source_identity)
                joined.append(BurstMessage(fragment.key, fragment.pinned_dividers[-1]))
        if not joined:
            return self
        return ArrivalBurst(kept + tuple(joined), now)

    def stack(self, window: PinsMessageHeader, pinned: PinnedHeader) -> StackedHeaders:
        """The earlier messages whose head is scrolled above the top row, the most recent
        `shown` of them, under a count line; none for a burst of one, or once the reader is
        above the burst (no head is above the top row then). The top row's own message pins
        its header as before and is not stacked twice."""
        if len(self.messages) < 2 or not pinned.width:
            return NO_STACK
        own = pinned.headers[-1:]
        above = [message for message in self.messages[:-1]
                 if message.header not in own
                 and (top := window.message_top(message.key)) is not None and top < window.scroll_y]
        if not above:
            return NO_STACK
        stacked = above[-self.shown:]
        count = Divider.titled(f"{len(self.messages)} new", MutedRole)
        return StackedHeaders((count, *(message.header for message in stacked)),
                              (above[0].key, *(message.key for message in stacked)))


NO_BURST = ArrivalBurst()


class HeaderPin:
    """The overlay a history window floats over its top row: the header of the message the reader
    is in, while that header is scrolled above, so the reader of a long message still sees who
    sent it to whom, and when; above it, a burst's stacked headers (`ArrivalBurst`). It draws
    the messages' own header blocks, as the flow does, and keeps no copy of a message. A plain
    mixin, as `LatestJumpBar` is: Textual's widget metaclass refuses an `ABC` base and Qt's
    shiboken metaclass clashes with one."""

    stacked: StackedHeaders = NO_STACK

    def pin(self, pinned: PinnedHeader, stacked: StackedHeaders = NO_STACK) -> None:
        """Draw the headers the window's top row needs, or none, in the column its message
        draws them in, so each sits and wraps exactly as the flow's own header does."""
        self.stacked = stacked
        headers = stacked.headers + pinned.headers[-1:]
        if headers:
            self.draw_pinned(headers, pinned.x, pinned.width)
        self.show_pin(bool(headers))

    def opened_at(self, index: int) -> FragmentKey | None:
        """The message the pin's `index`th drawn header opens: a stacked one's, none for the
        top row's own (the reader is already in that message)."""
        keys = self.stacked.keys
        return keys[index] if 0 <= index < len(keys) else None

    @abstractmethod
    def draw_pinned(self, headers: tuple[Divider, ...], x: int, width: int) -> None:
        """Draw `headers`, top to bottom, in the column at `x`, `width` wide, in the toolkit's unit."""

    @abstractmethod
    def show_pin(self, shown: bool) -> None:
        """Draw the pin, or stop drawing it."""


class PinsMessageHeader:
    """A history window that pins the header of the message on its top row. Both frontends
    answer which header that is through this one method: the top row's fragment decides
    (`FragmentRowUnderTop`), and with no drawn fragment there the live message does
    (`TopPage.pinned_header`). Listed after the window's own toolkit class, so the window's
    `top_page` and `live_message_header` answer."""

    sticky_header: HeaderPin
    arrival_burst: ArrivalBurst
    _restoring: bool
    pinned_scroll_y: float = 0.0
    """The offset the pin was last drawn at: a reader's own scroll up from it ends a burst."""

    def top_message_header(self) -> PinnedHeader:
        """The header of the message drawn on the window's top row, when that header is scrolled
        above it, with the column the flow draws it in."""
        return self.top_page().pinned_header(self)

    def repin_header(self) -> None:
        """Pin from where the reader is now. The window calls this on every scroll offset and
        every committed geometry change: a reflow, a filter, replaced rows or a restored tab can
        change the top row's message at an unchanged offset. Only the reader scrolls a window up:
        following, gliding and placing an arrival move it down or keep it (`layout_scroll`)."""
        burst = self.arrival_burst
        if burst.messages and self.scroll_y < self.pinned_scroll_y and not self._restoring:
            burst = self.arrival_burst = NO_BURST
        self.pinned_scroll_y = self.scroll_y
        pinned = self.top_message_header()
        self.sticky_header.pin(pinned, burst.stack(self, pinned) if burst.messages else NO_STACK)

    def open_pinned(self, index: int) -> bool:
        """The reader chose the pin's `index`th header: a stacked one scrolls to its message,
        whose head comes to the top row, and the burst ends. False for the top row's own."""
        key = self.sticky_header.opened_at(index)
        if key is None:
            return False
        top = self.message_top(key)
        self.arrival_burst = NO_BURST
        if top is not None:
            self.release_anchor()
            self.scroll_y = top
        self.repin_header()
        return True

    @abstractmethod
    def message_top(self, key: FragmentKey) -> float | None:
        """The offset that puts the drawn message `key`'s first row on the window's top row, in
        the window's unit; None when no drawn row holds it."""


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
