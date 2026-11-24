"""Where a history's reader is, named by what they read, and how each position is placed,
moved and released. A frontend's history window supplies the geometry these positions are
measured in; positions never cross from one window to another."""

from abc import ABC, abstractmethod
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import ClassVar

from toad.client.fragments import FragmentKey
from toad.client.history_preparation import NEWER_END, OLDER_END, PageEnd
from toad.client.history_state import LatestViewportRequest
from toad.client.prepared_pages import DrawnPage, PageFragmentRange, PreparedTranscriptPage, _DrawingStopped


class ReaderPage(DrawnPage):
    """A drawn page a position can be measured from: where it draws a source occurrence, and how
    tall it draws a fragment. A mixin beside a native widget, so it declares its hooks without
    ABC's metaclass."""

    @abstractmethod
    def fragment_row(self, key: FragmentKey, block: int) -> FragmentLocation: ...

    @abstractmethod
    def drawn_height(self, fragment) -> int: ...

    @classmethod
    @abstractmethod
    def drawn_for(cls, owner, prepared) -> ReaderPage:
        """A new, not yet shown page view of `prepared` in `owner`'s frontend."""

    @classmethod
    @asynccontextmanager
    async def acquire(
        cls, owner, prepared: PreparedTranscriptPage, *,
        end: PageEnd, pages: deque, current: Callable[[], bool],
    ) -> AsyncIterator[ReaderPage]:
        """Acquire the original prepared range, without selecting it a second time."""
        view = cls.drawn_for(owner, prepared)
        # Styled before it is drawn: a page drawn plain first rewraps under
        # the reader as each styled batch arrives.
        await owner.prepare_fragments(prepared.fragments_in_range, current,
                                      selected=owner.selected_categories, target=owner)
        if not current():
            raise _DrawingStopped
        async with AsyncExitStack() as acquisition:
            acquisition.push_async_callback(owner.remove_children, (view,))
            await end.mount(owner, view, pages)
            if not current():
                raise _DrawingStopped
            yield view
            acquisition.pop_all()



class ReaderWindow:
    """The native scrolling window a history's reader is in: its geometry, in the window's own
    unit, and the effects that place the reader. Each frontend's window implements it; a
    position is captured by one window and only ever placed in that window. A mixin listed
    after the native widget base, so the toolkit's own members win where they exist."""

    reader_position: ReaderPosition
    scroll_y: float

    @property
    @abstractmethod
    def follows_tail(self) -> bool: ...

    @property
    @abstractmethod
    def tail_scroll_y(self) -> float: ...

    @property
    @abstractmethod
    def scroll_revision(self) -> int: ...

    @property
    @abstractmethod
    def geometry_revision(self) -> int:
        """Counts every change to where this window's rows are: a change that leaves it as
        it was moved none, and needs no layout to show it."""

    @abstractmethod
    def top_page(self): ...

    @abstractmethod
    def placements(self, bodies) -> Iterator[tuple[object, int]]: ...

    @abstractmethod
    def placed_live_blocks(self) -> Iterator[tuple[object, int]]:
        """The live blocks the last layout placed that can hold the reader, with their rows."""

    @abstractmethod
    def holds(self, item) -> bool:
        """Whether a held native item is still drawn in this window."""

    @abstractmethod
    def row_of(self, item) -> int: ...

    @abstractmethod
    def drawn_pages(self) -> Iterator[ReaderPage]: ...

    @abstractmethod
    def release_anchor(self) -> None: ...

    @abstractmethod
    def layout_scroll(self): ...

    @abstractmethod
    def place_reader(self) -> bool: ...

    @abstractmethod
    def follow_latest(self) -> None: ...

    @abstractmethod
    def message_too_tall(self, height: int) -> bool: ...

    @abstractmethod
    def latest_limits(self, budget) -> tuple[int, int]: ...

    @abstractmethod
    def after_source_presented(self, callback, *arguments) -> None:
        """Run `callback` once the source just published has been painted."""

    @abstractmethod
    def request_reader_layout(self) -> None:
        """Ask for the layout that places the reader again."""


class FragmentNotLoaded(LookupError):
    """A requested source fragment has no loaded page or drawn location."""


class FragmentLocation(ABC):
    """A source fragment's drawn location, or the declared not-loaded result."""

    # Whether a page draws this occurrence somewhere; only the not-loaded result does not.
    located: ClassVar[bool] = True

    @abstractmethod
    def location(self) -> FragmentLocation: ...

    def tooltip(self) -> str | None:
        """The tooltip for the pointer over this location; None shows none."""
        return None

    def selected_by(self, cursor) -> bool:
        """Rest `cursor` here; whether there was a fragment to rest on."""
        return False

    def bodies(self) -> tuple[object, ...]:
        """The widgets a terminal draws this occurrence with; a location with none has none."""
        return ()

    @abstractmethod
    def for_layout(self, window: ReaderWindow, position: ReaderPosition) -> ReaderPosition: ...

    @abstractmethod
    def laid_out(self, window: ReaderWindow) -> bool: ...

    @abstractmethod
    def destination(self, window: ReaderWindow, fraction: float) -> float: ...

    @abstractmethod
    def find_in(self, pages: Iterator[ReaderPage], position: FragmentPosition) -> FragmentLocation: ...


class UnloadedFragment(FragmentLocation):
    """No loaded page draws a destination for this fragment occurrence."""

    located = False

    def location(self) -> FragmentLocation:
        raise FragmentNotLoaded("The source fragment has no drawn location")

    def for_layout(self, window: ReaderWindow, position: ReaderPosition) -> ReaderPosition:
        return position.without_holder(window)

    def laid_out(self, window: ReaderWindow) -> bool:
        return False

    def destination(self, window: ReaderWindow, fraction: float) -> float:
        raise FragmentNotLoaded("The reader's source fragment has no drawn destination yet")

    def find_in(self, pages: Iterator[ReaderPage], position: FragmentPosition) -> FragmentLocation:
        for page in pages:
            return page.fragment_row(position.key, position.block).find_in(pages, position)
        return self


class ReaderPosition(ABC):
    """Where the reader is in a history window, named by what they read.

    A scroll offset means nothing once rows above it change, so a position
    names the message the reader is on and how far the window's top is from
    that message's first row. The window keeps one while its history changes
    and every layout puts the reader back on it.
    """

    ranges: tuple[PageFragmentRange, ...] = ()

    @classmethod
    def of(cls, window: ReaderWindow) -> ReaderPosition:
        """Read where the reader is from what the window last laid out."""
        if window.follows_tail:
            return TailPosition()
        return window.top_page().reader_position(window)

    def required_presentations(self, presentation) -> tuple[object, ...]:
        """Source-addressed positions can be rebuilt without retaining native identity."""
        return ()

    def bodies(self, window: ReaderWindow) -> tuple[object, ...]:
        """The widgets layout must place to find this position."""
        return ()

    def for_layout(self, window: ReaderWindow, position: ReaderPosition) -> ReaderPosition:
        """The held position to use in this layout."""
        return position

    def laid_out(self, window: ReaderWindow) -> bool:
        """Whether the layout just made placed what this position is measured from."""
        bodies = self.bodies(window)
        return sum(1 for _ in window.placements(bodies)) == len(bodies)

    @abstractmethod
    def place(self, window: ReaderWindow) -> bool:
        """Scroll the window here in the layout just made; False when the layout is too short to reach it."""

    def moved(self, window: ReaderWindow, rows: float) -> ReaderPosition:
        """Shift the held message during a change; otherwise read the current viewport."""
        return window.history_change.moved(self, window, rows)

    def shifted(self, rows: float) -> ReaderPosition:
        """This position displaced by an explicit number of rows; positions not tied to an
        offset stay themselves."""
        return self

    def left_tail(self, window: ReaderWindow) -> ReaderPosition:
        """The position after the reader stopped following the latest message."""
        return ReaderPosition.of(window)

    def parked(self, window: ReaderWindow, contents) -> ParkedPosition:
        ranges = tuple(page_range for history in contents.line_histories()
                       for page_range in history.capture_reader_ranges())
        return ParkedPosition(self, ranges)

    def joined_tail(self) -> ReaderPosition:
        """The position after the reader chose to follow the latest message."""
        return TailPosition()

    def joins_tail(self, window: ReaderWindow) -> bool:
        """Whether placing this puts the reader on the latest row: a window with its own way
        there (Qt's glide) takes it only then."""
        return False

    def arrived(self, page: ReaderPage, key: FragmentKey) -> ReaderPosition:
        """The position after a message arrived at the followed end: only following hands it the reader."""
        return self

    def revealed(self, window: ReaderWindow) -> None:
        """Arriving rows rose a step: only a reader following the tail goes down with them."""

    def placed(self, window: ReaderWindow, reached: bool) -> ReaderPosition:
        """What the window keeps after a layout placed this: itself while the history is still changing.

        A history too short to reach it (its matches or pages are still being
        read) keeps it until one is long enough.
        """
        return self.moved(window, 0) if reached else self

    def without_holder(self, window: ReaderWindow) -> ReaderPosition:
        """Keep an unfinished change's destination; otherwise name the currently drawn message."""
        return self.moved(window, 0)

    def preparation_start(self, history) -> tuple[int, int]:
        """Where preparation begins when no message supplies a more exact place."""
        return 0, history.pages[0].prepared.start

    async def prepare(self, history, current, target, selected, rows_needed, limit: int):
        """Fill the reader's earlier rows, then the later rows in the remaining budget."""
        start = self.preparation_start(history)
        anchor = history.pages[start[0]].prepared
        _, limit = await OLDER_END.walk(
            history, current, target, selected, start,
            history.window.latest_limits(history.budget)[0], limit,
        )
        earlier = anchor.capture_range()
        rows_needed, limit = await NEWER_END.walk(
            history, current, target, selected, start, rows_needed, limit,
        )
        anchor.set_fragment_range(slice(min(anchor.start, earlier.start),
                                        max(anchor.stop, earlier.stop)))
        return rows_needed, limit

    def prepare_history(self, history) -> None:
        """Give a history about to be mounted the page ranges this position needs."""
        history.set_reader_ranges(self.ranges)

    def source_settled(self, window: ReaderWindow) -> None:
        """A source publication settled; only a held destination waits for one."""

    async def source_arrived(self, history) -> bool:
        """Whether this position fetched the newer source itself; only End does."""
        return False

    def release(self, window: ReaderWindow) -> None:
        """Nothing will publish again; only a held destination has anything to let go."""

    def placed_by_layout(self, window: ReaderWindow) -> bool:
        """The layout just made puts the reader on the window's kept position."""
        return window.place_reader()


@dataclass(frozen=True)
class TailPosition(ReaderPosition):
    """Following the latest message."""

    def preparation_start(self, history) -> tuple[int, int]:
        return len(history.pages) - 1, len(history.pages[-1].prepared.fragments)

    async def prepare(self, history, current, target, selected, rows_needed, limit: int):
        return await OLDER_END.walk(history, current, target, selected,
                                  self.preparation_start(history), rows_needed, limit)

    def place(self, window: ReaderWindow) -> bool:
        if not window.follows_tail:
            window.anchor()
        window.scroll_y = window.tail_scroll_y
        return True

    def joins_tail(self, window: ReaderWindow) -> bool:
        return True

    def revealed(self, window: ReaderWindow) -> None:
        if window.follows_tail:
            with window.layout_scroll():
                window.scroll_y = window.tail_scroll_y

    def joined_tail(self) -> ReaderPosition:
        return self

    def arrived(self, page: ReaderPage, key: FragmentKey) -> ReaderPosition:
        return ArrivalPosition(page, key)


class OffsetPosition(ReaderPosition):
    """A position inside the history, placed by its destination in the current layout."""

    @abstractmethod
    def destination(self, window: ReaderWindow) -> float:
        """The scroll that shows this position in the layout just made."""

    def place(self, window: ReaderWindow) -> bool:
        destination = self.destination(window)
        if window.follows_tail:
            window.release_anchor()
        window.scroll_y = destination
        return window.scroll_y == destination

    def shifted(self, rows: float) -> ReaderPosition:
        return replace(self, y=self.y + rows)


@dataclass(frozen=True)
class RowPosition(OffsetPosition):
    """A window that draws no message: only the scroll offset is known."""

    y: float

    def destination(self, window: ReaderWindow) -> float:
        return self.y


@dataclass(frozen=True)
class FragmentPosition(OffsetPosition):
    """A message of a line-drawn history.

    The source child and fraction within it survive changes to sibling blocks.
    Its captured child height converts explicit reader motion to that coordinate.
    Its source key survives eviction and re-preparation into fresh fragments.
    """

    key: FragmentKey
    fraction: float
    height: int
    block: int = field(kw_only=True)

    def page(self, window: ReaderWindow) -> FragmentLocation:
        """The drawn location of this occurrence, or its not-loaded state."""
        return UnloadedFragment().find_in(iter(window.drawn_pages()), self)

    def bodies(self, window: ReaderWindow) -> tuple[object, ...]:
        return self.page(window).bodies()

    def for_layout(self, window: ReaderWindow, position: ReaderPosition) -> ReaderPosition:
        return self.page(window).for_layout(window, position)

    def laid_out(self, window: ReaderWindow) -> bool:
        # A page whose messages changed after layout measured it has rows for
        # the earlier ones; the layout that change asked for places this.
        return self.page(window).laid_out(window)

    def preparation_start(self, history) -> tuple[int, int]:
        return next(((index, boundary) for index, page in enumerate(history.pages)
                     for boundary, fragment in enumerate(page.prepared.fragments)
                     if fragment.key == self.key),
                    super().preparation_start(history))

    def destination(self, window: ReaderWindow) -> float:
        return self.page(window).destination(window, self.fraction)

    def shifted(self, rows: float) -> ReaderPosition:
        return replace(self, fraction=self.fraction + rows / self.height)


class UnshownReader(ReaderPosition):
    """The reader of a window the layout does not draw: nothing is measured from it or placed."""

    def place(self, window: ReaderWindow) -> bool:
        return False

    def placed_by_layout(self, window: ReaderWindow) -> bool:
        return False


UNSHOWN_READER = UnshownReader()


class NativeReaderHolder:
    """This position retains native widgets or pagers, not just a source key."""

    def required_presentations(self, presentation) -> tuple[object, ...]:
        return (presentation,)


@dataclass(frozen=True)
class BlockPosition(NativeReaderHolder, OffsetPosition):
    """A live block (an answer being written, a tool call, a channel message): `row` is its window row when read."""

    block: object
    row: int
    y: float

    @classmethod
    def of(cls, window: ReaderWindow) -> ReaderPosition:
        """The topmost live block the last layout placed, else the bare scroll offset.

        Candidates come from the published frame but are measured in the layout just
        made, so a block published last frame and not placed now (a CLI draft hidden
        since) is no candidate. Containers of other blocks do not hold the reader.
        """
        placed = (cls(block, row, window.scroll_y) for block, row in window.placed_live_blocks())
        return min(placed, key=lambda position: position.row, default=RowPosition(window.scroll_y))

    def bodies(self, window: ReaderWindow) -> tuple[object, ...]:
        return (self.block,)

    def for_layout(self, window: ReaderWindow, position: ReaderPosition) -> ReaderPosition:
        if window.holds(self.block):
            return position
        return position.without_holder(window)

    def laid_out(self, window: ReaderWindow) -> bool:
        return any(window.placements(self.bodies(window)))

    def destination(self, window: ReaderWindow) -> float:
        return window.row_of(self.block) + self.y - self.row


@dataclass(frozen=True)
class ArrivalPosition(NativeReaderHolder, OffsetPosition):
    """A message that just arrived at the followed end, on the page that draws it.

    One that fits in the window follows the tail as before. One taller than
    the window is placed with its first row at the window's top instead of
    its last, so the reader sees it arrive from its head; following stops
    there, as when the reader scrolls up to read. The page is a geometry
    target, so the layout that adds the message also places it.
    """

    page: ReaderPage
    key: FragmentKey

    def location(self) -> FragmentLocation:
        return self.page.fragment_row(self.key, 0)

    def bodies(self, window: ReaderWindow) -> tuple[object, ...]:
        return (self.page,)

    def for_layout(self, window: ReaderWindow, position: ReaderPosition) -> ReaderPosition:
        if window.holds(self.page):
            return position
        return position.without_holder(window)

    def laid_out(self, window: ReaderWindow) -> bool:
        return self.location().laid_out(window)

    def destination(self, window: ReaderWindow) -> float:
        return self.location().destination(window, 0.0)

    def tall(self, window: ReaderWindow) -> bool:
        """Whether the message is taller than the window, in the layout just made."""
        return window.message_too_tall(self.page.drawn_height(self.location().location().fragment))

    def joins_tail(self, window: ReaderWindow) -> bool:
        """An arrival not drawn yet, or one that fits in the window, follows the tail."""
        return not (self.laid_out(window) and self.tall(window))

    def place(self, window: ReaderWindow) -> bool:
        if self.tall(window):
            return super().place(window)
        return TailPosition().place(window)

    def revealed(self, window: ReaderWindow) -> None:
        # A tick can come before the layout that draws the arrival: until then it has no row
        # to measure, and the layout that adds it places the reader (FragmentNotLoaded,
        # 2026-11-06 13:25).
        if self.laid_out(window) and not self.tall(window):
            TailPosition().revealed(window)

    def shifted(self, rows: float) -> ReaderPosition:
        # Kept through its change, so every layout of the change places it
        # from its own page; afterwards the window reads where the reader is.
        # The reader leaving the tail replaces it through left_tail.
        return self


class Settlement:
    """Where a held destination's source stands: its layout is placed once, after the source has painted."""

    def settled(self, hold: HeldReaderDestination, window: ReaderWindow) -> Settlement:
        """The source settled; only an unsettled hold waits for the refresh that paints it."""
        return self

    def placed(self, hold: HeldReaderDestination, window: ReaderWindow, reached: bool) -> ReaderPosition:
        """Only a ready settlement may release a reached, measured hold."""
        return hold


class Unsettled(Settlement):
    def settled(self, hold: HeldReaderDestination, window: ReaderWindow) -> Settlement:
        window.after_source_presented(hold.source_geometry_ready, window)
        return Settlement()


class Ready(Settlement):
    def placed(self, hold: HeldReaderDestination, window: ReaderWindow, reached: bool) -> ReaderPosition:
        if reached and all(page.rows_measured for page in window.drawn_pages()):
            return hold.released()
        return hold


@dataclass(eq=False)
class HoldProgress:
    """One hold's settlement: the hold is a value, its progress is the one thing that changes."""

    state: Settlement = field(default_factory=Unsettled)


@dataclass(frozen=True, kw_only=True)
class HeldReaderDestination:
    """A reader destination retained through intermediate source layouts."""

    progress: HoldProgress = field(default_factory=HoldProgress, compare=False, repr=False)

    def source_settled(self, window: ReaderWindow) -> None:
        """Wait for a completed source paint before admitting its destination layout."""
        self.progress.state = self.progress.state.settled(self, window)

    def source_geometry_ready(self, window: ReaderWindow) -> None:
        if window.reader_position is not self:
            return
        self.progress.state = Ready()
        window.request_reader_layout()

    def placed(self, window: ReaderWindow, reached: bool) -> ReaderPosition:
        return self.progress.state.placed(self, window, reached)

    def release(self, window: ReaderWindow) -> None:
        self.source_settled(window)

    @abstractmethod
    def released(self) -> ReaderPosition: ...


@dataclass(frozen=True)
class ParkedPosition(HeldReaderDestination, ReaderPosition):
    """A position the reader left with its tab, waiting for the history to be drawn again.

    It carries the page ranges that were loaded, so a rebuilt history loads
    the same messages, and is placed as the position it parks.
    """

    position: ReaderPosition
    ranges: tuple[PageFragmentRange, ...]

    def required_presentations(self, presentation) -> tuple[object, ...]:
        return self.position.required_presentations(presentation)

    async def prepare(self, history, current, target, selected, rows_needed, limit: int):
        return await self.position.prepare(history, current, target, selected, rows_needed, limit)

    def bodies(self, window: ReaderWindow) -> tuple[object, ...]:
        return self.position.bodies(window)

    def for_layout(self, window: ReaderWindow, position: ReaderPosition) -> ReaderPosition:
        return self.position.for_layout(window, position)

    def laid_out(self, window: ReaderWindow) -> bool:
        return self.position.laid_out(window)

    def place(self, window: ReaderWindow) -> bool:
        return self.position.place(window)

    def shifted(self, rows: float) -> ReaderPosition:
        return self.position.shifted(rows)

    def parked(self, window: ReaderWindow, contents) -> ParkedPosition:
        return self

    def without_holder(self, window: ReaderWindow) -> ReaderPosition:
        # Its pages are loaded after the tab returns.
        return self

    def released(self) -> ReaderPosition:
        return self.position


@dataclass(frozen=True)
class LatestPosition(NativeReaderHolder, HeldReaderDestination, TailPosition):
    """The newest source row, held until the publication that supplies it settles."""

    revision: int
    sources: tuple[tuple[object, object], ...]
    awaits_source_advance: bool

    @classmethod
    def hold(cls, window: ReaderWindow) -> LatestPosition:
        window.anchor()
        sources = tuple((history, history.page_source.through) for history in window.histories)
        latest = cls(
            window.scroll_revision,
            sources,
            not any(NEWER_END.visible_more(history) for history, _through in sources),
        )
        window.reader_position = latest
        return latest

    def current(self, window: ReaderWindow) -> bool:
        return window.reader_position is self and window.scroll_revision == self.revision

    def restore(self, window: ReaderWindow) -> None:
        if self.current(window):
            window.follow_latest()

    def source_settled(self, window: ReaderWindow) -> None:
        if (self.awaits_source_advance
                and all(history.page_source.through == through for history, through in self.sources)):
            return
        super().source_settled(window)

    async def source_arrived(self, history) -> bool:
        return await history.jump_latest(LatestViewportRequest(self))

    def release(self, window: ReaderWindow) -> None:
        if window.reader_position is self:
            window.reader_position = self.released()
            window.place_reader()

    def arrived(self, page: ReaderPage, key: FragmentKey) -> ReaderPosition:
        # End was pressed: the newest row stays the destination until its source settles.
        return self

    def released(self) -> ReaderPosition:
        return TailPosition()
