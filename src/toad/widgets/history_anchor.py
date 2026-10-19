"""The history window: where its reader is, and keeping them there while the history changes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from functools import cached_property
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
import asyncio
from typing import TYPE_CHECKING
from weakref import WeakSet

from textual.widget import Widget
from toad.widget_view import WorkspaceHosted
from textual import events
from textual.containers import VerticalScroll
from toad.widgets.presentation_window import DirectionalPreparation, PresentationBudget, OLDER_END, NEWER_END
from toad.transcript_state import LatestViewportRequest

if TYPE_CHECKING:
    from toad.transcript_preparation import PageFragmentRange
    from toad.transcript_source_preparation import TranscriptSourcePreparation
    from toad.widgets.conversation import Contents


class ReaderPosition(ABC):
    """Where the reader is in a history window, named by what they read.

    A scroll offset means nothing once rows above it change, so a position
    names the message the reader is on and how far the window's top is from
    that message's first row. The window keeps one while its history changes
    and every layout puts the reader back on it.
    """

    ranges: tuple["PageFragmentRange", ...] = ()

    @classmethod
    def of(cls, window: "HistoryWindow") -> "ReaderPosition":
        """Read where the reader is from what the window last laid out."""
        if window.follows_tail:
            return TailPosition()
        y = window.scroll_y
        reading = min(((first, page) for page in window.drawn_pages()
                       if page.line_count and (first := window.placed_row(page)) is not None
                       and first + page.line_count > y),
                      key=lambda placed: max(y, placed[0]), default=None)
        if reading is not None:
            first, page = reading
            span = page.fragment_at(max(0, int(y - first)))
            fragment = span.fragment
            return FragmentPosition(fragment.arrival_position, (y - first - span.first) / span.height,
                                    span.height, part=fragment.part_position.index, block=span.index)
        if (position := BlockPosition.of(window)) is not None:
            return position
        return RowPosition(y)

    def bodies(self, window: "HistoryWindow") -> tuple[Widget, ...] | None:
        """The widgets layout must place to find this position; None when nothing drawn holds it."""
        return ()

    def laid_out(self, window: "HistoryWindow") -> bool:
        """Whether the layout just made placed what this position is measured from."""
        bodies = self.bodies(window)
        return bodies is not None and all(window.placed_row(body) is not None for body in bodies)

    @abstractmethod
    def place(self, window: "HistoryWindow") -> bool:
        """Scroll the window here in the layout just made; False when the layout is too short to reach it."""

    def moved(self, window: "HistoryWindow", rows: float) -> "ReaderPosition":
        """Shift the held message during a change; otherwise read the current viewport."""
        return self.shifted(rows) if window.history_change is not None else ReaderPosition.of(window)

    @abstractmethod
    def shifted(self, rows: float) -> ReaderPosition:
        """This position displaced by an explicit number of rows."""

    def left_tail(self, window: "HistoryWindow") -> "ReaderPosition":
        """The position after the reader stopped following the latest message."""
        return ReaderPosition.of(window)

    def parked(self, window: "HistoryWindow", contents: Contents) -> ParkedPosition:
        ranges = tuple(page_range for history in contents.line_histories()
                       for page_range in history.capture_reader_ranges())
        return ParkedPosition(self, ranges)

    def joined_tail(self) -> "ReaderPosition":
        """The position after the reader chose to follow the latest message."""
        return TailPosition()

    def placed(self, window: "HistoryWindow", reached: bool) -> "ReaderPosition":
        """What the window keeps after a layout placed this: itself while the history is still changing.

        A history too short to reach it (its matches or pages are still being
        read) keeps it until one is long enough.
        """
        if not reached:
            return UnreachedPosition(self)
        return self.moved(window, 0)

    def without_holder(self, window: "HistoryWindow") -> "ReaderPosition":
        """Keep an unfinished change's destination; otherwise name the currently drawn message."""
        return self.moved(window, 0)

    def preparation_start(self, history) -> tuple[int, int]:
        """Where preparation begins when no message supplies a more exact place."""
        return 0, history.pages[0].prepared.start

    async def prepare(self, history, current, target, selected, rows_needed, limit):
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

    def prepare_history(self, history: "TranscriptSourcePreparation") -> None:
        """Give a history about to be mounted the page ranges this position needs."""
        history.set_reader_ranges(self.ranges)


@dataclass(frozen=True)
class TailPosition(ReaderPosition):
    """Following the latest message."""

    def preparation_start(self, history) -> tuple[int, int]:
        return len(history.pages) - 1, len(history.pages[-1].prepared.fragments)

    async def prepare(self, history, current, target, selected, rows_needed, limit):
        return await OLDER_END.walk(history, current, target, selected,
                                  self.preparation_start(history), rows_needed, limit)

    def place(self, window: "HistoryWindow") -> bool:
        if not window.follows_tail:
            window.anchor()
        window.scroll_y = window.max_scroll_y
        return True

    def shifted(self, rows: float) -> ReaderPosition:
        return self

    def joined_tail(self) -> ReaderPosition:
        return self


class OffsetPosition(ReaderPosition):
    """A position inside the history, placed by its destination in the current layout."""

    @abstractmethod
    def destination(self, window: "HistoryWindow") -> float:
        """The scroll that shows this position in the layout just made."""

    def place(self, window: "HistoryWindow") -> bool:
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

    def destination(self, window: "HistoryWindow") -> float:
        return self.y


@dataclass(frozen=True)
class FragmentPosition(OffsetPosition):
    """A message of a line-drawn history.

    The source child and fraction within it survive changes to sibling blocks.
    Its captured child height converts explicit reader motion to that coordinate;
    the saved arrival and part positions name the message after a reload.
    """

    position: int | str
    fraction: float
    height: int
    part: int = field(kw_only=True)
    block: int = field(kw_only=True)

    def page(self, window: "HistoryWindow"):
        """The displayed page that holds this message."""
        return next((page for page in window.drawn_pages()
                     if page.fragment_row(self.position, self.part, self.block) is not None), None)

    def bodies(self, window: "HistoryWindow") -> tuple[Widget, ...] | None:
        page = self.page(window)
        return None if page is None else (page,)

    def laid_out(self, window: "HistoryWindow") -> bool:
        # A page whose messages changed after layout measured it has rows for
        # the earlier ones; the layout that change asked for places this.
        return super().laid_out(window) and self.page(window).rows_measured

    def preparation_start(self, history) -> tuple[int, int]:
        return next(((index, boundary) for index, page in enumerate(history.pages)
                     for boundary, fragment in enumerate(page.prepared.fragments)
                     if fragment.matches_position(self.position, self.part)),
                    super().preparation_start(history))

    def destination(self, window: "HistoryWindow") -> float:
        page = self.page(window)
        span = page.fragment_row(self.position, self.part, self.block)
        # A hidden child or message places the reader on the next one drawn.
        return window.row_of(page) + span.first + (self.fraction * span.height if span.drawn else 0)

    def shifted(self, rows: float) -> ReaderPosition:
        return replace(self, fraction=self.fraction + rows / self.height)


@dataclass(frozen=True)
class BlockPosition(OffsetPosition):
    """A live block (an answer being written, a tool call, a channel message): `row` is its window row when read."""

    block: Widget
    row: int
    y: float

    @classmethod
    def of(cls, window: "HistoryWindow") -> "BlockPosition | None":
        """The topmost drawn live block; containers of other blocks do not hold the reader."""
        from toad.block_navigation import ConversationBlock

        visible = window.screen._compositor.published_widgets
        blocks = [widget for widget in visible
                  if isinstance(widget, ConversationBlock) and window in widget.ancestors]
        holders = {ancestor for block in blocks for ancestor in block.ancestors}
        block = min(window.visible_history_items(block for block in blocks if block not in holders),
                    key=lambda node: visible[node][0].y, default=None)
        return None if block is None else cls(block, window.row_of(block), window.scroll_y)

    def bodies(self, window: "HistoryWindow") -> tuple[Widget, ...] | None:
        return (self.block,) if self.block.is_attached and window.displays(self.block) else None

    def destination(self, window: "HistoryWindow") -> float:
        return window.row_of(self.block) + self.y - self.row


@dataclass(frozen=True)
class UnreachedPosition(ReaderPosition):
    """A position no layout has reached yet: the history is still too short, or is not drawn.

    Layout places it until it is reached. The reader moving first chooses a
    new place instead.
    """

    position: ReaderPosition

    async def prepare(self, history, current, target, selected, rows_needed, limit):
        return await self.position.prepare(history, current, target, selected, rows_needed, limit)

    def bodies(self, window: "HistoryWindow") -> tuple[Widget, ...] | None:
        return self.position.bodies(window)

    def laid_out(self, window: "HistoryWindow") -> bool:
        return self.position.laid_out(window)

    def place(self, window: "HistoryWindow") -> bool:
        return self.position.place(window)

    def shifted(self, rows: float) -> ReaderPosition:
        return self.position.shifted(rows)

    def placed(self, window: "HistoryWindow", reached: bool) -> ReaderPosition:
        return self.position.placed(window, reached) if reached else self

    def without_holder(self, window: "HistoryWindow") -> ReaderPosition:
        return self.position.without_holder(window)


class HeldReaderDestination:
    """A reader destination retained through intermediate source layouts."""

    source_settlement_scheduled = False
    source_ready = False

    @classmethod
    def held(cls, window: "HistoryWindow") -> "HeldReaderDestination | None":
        position = window.reader_position
        return position if isinstance(position, cls) else None

    @classmethod
    def settle(cls, window: "HistoryWindow") -> None:
        destination = cls.held(window)
        if (destination is not None
                and all(history.state.accepts_source_work for history in window.histories)):
            destination.source_settled(window)

    def source_settled(self, window: "HistoryWindow") -> None:
        """Wait for a completed source paint before admitting its destination layout."""
        if self.source_settlement_scheduled or self.source_ready:
            return
        object.__setattr__(self, "source_settlement_scheduled", True)
        window.call_after_refresh(self.source_geometry_ready, window)

    def source_geometry_ready(self, window: "HistoryWindow") -> None:
        if window.reader_position is not self:
            return
        object.__setattr__(self, "source_ready", True)
        window.refresh(layout=True)

    def placed(self, window: "HistoryWindow", reached: bool) -> ReaderPosition:
        measured = all(page.rows_measured for page in window.drawn_pages())
        if reached and self.source_ready and measured:
            return self.released()
        return self

    async def source_arrived(self, history: "TranscriptSourcePreparation") -> bool:
        return False

    def release(self, window: "HistoryWindow") -> None:
        self.source_settled(window)

    @abstractmethod
    def released(self) -> ReaderPosition: ...


@dataclass(frozen=True)
class ParkedPosition(HeldReaderDestination, UnreachedPosition):
    """A position the reader left with its tab, waiting for the history to be drawn again.

    It carries the page ranges that were loaded, so a rebuilt history loads
    the same messages.
    """

    ranges: tuple["PageFragmentRange", ...]

    def parked(self, window: "HistoryWindow", contents: Contents) -> ParkedPosition:
        return self

    def without_holder(self, window: "HistoryWindow") -> ReaderPosition:
        # Its pages are loaded after the tab returns.
        return self

    def released(self) -> ReaderPosition:
        return self.position


@dataclass(frozen=True)
class LatestPosition(HeldReaderDestination, TailPosition):
    """The newest source row, held until the publication that supplies it settles."""

    revision: int
    sources: tuple[tuple["TranscriptSourcePreparation", object], ...]
    awaits_source_advance: bool

    @classmethod
    def hold(cls, window: "HistoryWindow") -> "LatestPosition":
        window.anchor()
        sources = tuple((history, history.page_source.through) for history in window.histories)
        latest = cls(
            window.scroll_revision,
            sources,
            not any(NEWER_END.visible_more(history) for history, _through in sources),
        )
        window.reader_position = latest
        return latest

    def current(self, window: "HistoryWindow") -> bool:
        return window.reader_position is self and window.scroll_revision == self.revision

    def restore(self, window: "HistoryWindow") -> None:
        if self.current(window):
            window.follow_latest()

    def source_settled(self, window: "HistoryWindow") -> None:
        if (self.awaits_source_advance
                and all(history.page_source.through == through for history, through in self.sources)):
            return
        super().source_settled(window)

    async def source_arrived(self, history: "TranscriptSourcePreparation") -> bool:
        return await history._jump_latest(LatestViewportRequest(self))

    def release(self, window: "HistoryWindow") -> None:
        if window.reader_position is self:
            window.reader_position = self.released()
            window.place_reader()

    def released(self) -> ReaderPosition:
        return TailPosition()


@dataclass(eq=False)
class HistoryChange:
    """One change to what a history window draws, and the layout that shows it."""

    layout_ready: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    layout_requests: int = field(default=0, init=False)
    """How many layouts this change has requested; a layout answers those made before it started."""
    laid_out: bool = field(default=False, init=False)
    """Whether a layout has shown this change's final rows (and put the reader on the kept position)."""

    def request_layout(self, window: "HistoryWindow") -> None:
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


class HistoryWindow(WorkspaceHosted, VerticalScroll):
    """A document owns reader intent and ends its pointer-scroll route.

    Nested controls receive the native event first. Once it reaches this
    viewport, moving or clamping completes it; workspace ancestors cannot
    scroll this document and must not hold its input at a reached boundary.
    """

    def _scroll_or_prepare(self, distance: float, action, *args) -> None:
        # At a lazy edge, lookahead requests the missing history. Otherwise
        # the native action moves the reader.
        if not self.lookahead.request_boundary(distance):
            action(*args)

    def action_scroll_up(self) -> None:
        self._scroll_or_prepare(-1, super().action_scroll_up)

    def action_scroll_down(self) -> None:
        self._scroll_or_prepare(1, super().action_scroll_down)

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.prevent_default()
        self._scroll_or_prepare(-self.app.scroll_sensitivity_y, super()._on_mouse_scroll_up, event)
        event.stop()

    def action_page_up(self) -> None:
        self._scroll_or_prepare(-max(1, self.scrollable_content_region.height), super().action_page_up)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.prevent_default()
        self._scroll_or_prepare(self.app.scroll_sensitivity_y, super()._on_mouse_scroll_down, event)
        event.stop()

    def action_page_down(self) -> None:
        self._scroll_or_prepare(max(1, self.scrollable_content_region.height), super().action_page_down)

    def _on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        event.prevent_default()
        super()._on_mouse_scroll_left(event)
        event.stop()

    def _on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        event.prevent_default()
        super()._on_mouse_scroll_right(event)
        event.stop()

    CACHE_SUBTREE_GEOMETRY = True
    scroll_revision = 0
    _restoring = False
    reader_position: ReaderPosition = TailPosition()
    """The position held during history changes and across tab returns."""
    history_change: HistoryChange | None = None
    _history_mutation_root: Widget | None = None

    def action_scroll_end(self) -> None:
        self.jump_to_latest()

    def jump_to_latest(self) -> None:
        """Follow the source tail, including pages outside the mounted window."""
        latest = LatestPosition.hold(self)
        self.destination()
        for history in tuple(self.histories):
            if NEWER_END.visible_more(history):
                history.request_latest(latest)

    def tail_follow_changed(self) -> None:
        """Project the canonical tail-follow state in a specialized window."""

    @property
    def shown(self) -> bool:
        """Whether layout draws this window: its screen is the current one and nothing above it is hidden."""
        return (self.is_attached and self.screen.is_current
                and all(node.display for node in self.ancestors_with_self if isinstance(node, Widget)))

    def displays(self, widget: Widget) -> bool:
        """Whether a widget inside this window is displayed, with everything between them."""
        node = widget
        while node is not self:
            if not node.display or not isinstance(node.parent, Widget):
                return False
            node = node.parent
        return True

    def placed_row(self, widget: Widget) -> int | None:
        """The widget's first row in this window's laid-out content, or None if layout did not place it.

        Viewport layout places what is on screen plus the screen's declared
        geometry targets, so None means the widget is off screen.
        """
        row = 0
        node = widget
        geometry = self.screen._compositor._layout_map
        while node is not self:
            if (placed := geometry.get(node)) is None:
                return None
            row += placed.virtual_region.y
            if not isinstance(node.parent, Widget):
                break
            node = node.parent
        return row

    def row_of(self, widget: Widget) -> int:
        """The row of a widget layout must have placed: one on screen, or one the kept position names."""
        if (row := self.placed_row(widget)) is None:
            raise LookupError(f"{widget!r} is not placed in {self!r}'s layout; "
                              "a reader position's widgets must be visible or declared geometry targets")
        return row

    def drawn_pages(self):
        """Pages in this window's published viewport, not all loaded history."""
        from toad.widgets.transcript_history import TranscriptPageView

        pages = (widget for widget in self.screen._compositor.published_widgets
                 if isinstance(widget, TranscriptPageView))
        return (page for page in self.visible_history_items(pages) if self.displays(page))

    def keep_reader(self) -> None:
        """What this window draws is about to change: layout keeps the reader where they are now."""
        self.screen.reader_kept()

    def park_reader(self, contents: Contents) -> ParkedPosition:
        """The reader's tab is being left: keep their place until its history is drawn again."""
        self.app.animator.force_stop_animation(self, "scroll_y", complete=False)
        self.scroll_target_y = self.scroll_y
        parked = self.reader_position.parked(self, contents)
        self.reader_position = parked
        return parked

    def prepare_history(self, history: "TranscriptSourcePreparation") -> None:
        """A history about to be mounted loads the page ranges the kept position needs."""
        self.reader_position.prepare_history(history)
        if self.follows_tail:
            self.lookahead.destination(self.outer_size.height, pages_read=len(history.pages))

    def latest_limits(self, budget: PresentationBudget) -> tuple[int, int]:
        """One native destination's row capacity and bounded fragment budget."""
        return (self.presentation_budget.runway_rows(self.outer_size.height),
                self.lookahead.destination_batch(budget, self.outer_size.height))

    def history_geometry_targets(self) -> tuple[Widget, ...]:
        """The widgets the kept position is measured from: layout places them even off screen."""
        position = self.reader_for_layout()
        return () if position is None else position.bodies(self)

    def reader_for_layout(self) -> ReaderPosition | None:
        """The kept position, when this layout can place it."""
        position = self.reader_position
        if not self.shown:
            return None
        if position.bodies(self) is None:
            self.reader_position = position.without_holder(self)
            return None
        return position

    def place_reader(self) -> bool:
        """Put the reader on the kept position in the layout just made; True when that scrolled the window.

        A layout runs over loop turns and the reader can scroll meanwhile.
        Their movement shifts the kept position, so the position kept now is
        the one placed. One that names widgets this layout did not measure
        (kept after the layout started) is placed by the layout that follows.
        """
        position = self.reader_position
        if not position.laid_out(self):
            return False
        previous = self.scroll_y
        with self.layout_scroll():
            self.reader_position = position.placed(self, position.place(self))
        return self.scroll_y != previous

    @contextmanager
    def layout_scroll(self):
        """Scrolling inside is layout keeping the reader in place, not the reader moving.

        A running scroll animation and the measured travel are shifted by the
        same rows, so the reader's own movement continues from the new place.
        """
        restoring = self._restoring
        previous = self.scroll_y
        destination = self.scroll_target_y
        self._restoring = True
        try:
            yield
        finally:
            try:
                if not restoring:
                    if rows := self.scroll_y - previous:
                        self.app.animator.transform_running_animation(
                            self, "scroll_y", lambda value: value + rows,
                        )
                        self.scroll_target_y = destination + rows
                    self.lookahead.relocated(rows)
            finally:
                self._restoring = restoring

    def follow_latest(self) -> None:
        """Follow the latest message on a request the reader already made; not a new movement."""
        with self.layout_scroll():
            self.anchor()

    def retire_presentation_wait(self) -> None:
        """Release a change whose scene no longer promises another frame."""
        if (change := self.history_change) is not None:
            change.release()

    def on_mount(self) -> None:
        self.screen.history_windows.add(self)
        self.request_preparation()

    def on_unmount(self) -> None:
        self.retire_presentation_wait()
        self.settle_preparation()
        self.screen.history_windows.discard(self)

    def prepare_viewport(self) -> None:
        """Window subclasses publish work that depends on committed geometry."""

    @cached_property
    def presentation_budget(self) -> PresentationBudget:
        return PresentationBudget(buffer_viewports=self.app.settings.ui.history_buffer_viewports)

    @cached_property
    def lookahead(self) -> DirectionalPreparation:
        """Measured scroll travel; it sizes how far ahead histories prepare."""
        return DirectionalPreparation(self)

    @property
    def rows_per_fragment(self) -> float:
        """Average drawn rows per loaded fragment, for converting rows to fragments."""
        rows = items = 0
        for history in self.histories:
            drawn_rows, drawn_items = history.drawn_extent
            rows += drawn_rows
            items += drawn_items
        return rows / items if rows and items else max(1, self.outer_size.height)

    def request_preparation(self) -> None:
        """Histories prepare around the reader after the next published frame."""
        if not self.is_attached or self.is_leaving:
            return
        for history in tuple(self.histories):
            history.request_preparation()
        self.screen.frame_presentation.defer(self, self.prepare_viewport)

    def destination(self) -> None:
        """End: prepare the destination in one burst, not every page between."""
        self.lookahead.observe(self.scroll_y)
        self.lookahead.destination(self.outer_size.height)
        self.request_preparation()

    _settle_timer = None

    def _schedule_settle(self) -> None:
        if self._settle_timer is not None:
            self._settle_timer.stop()
        self._settle_timer = self.set_timer(self.lookahead.idle_seconds, self._settle)

    def _settle(self) -> None:
        self._settle_timer = None
        self.lookahead.settle()
        self.request_preparation()

    def settle_preparation(self) -> None:
        """A hidden or closing window stops predicting travel."""
        if self._settle_timer is not None:
            self._settle_timer.stop()
            self._settle_timer = None
        self.lookahead.settle()

    @cached_property
    def history_lock(self) -> asyncio.Lock:
        return asyncio.Lock()

    @cached_property
    def histories(self) -> WeakSet[TranscriptSourcePreparation]:
        """Mounted pagers register themselves; status checks need no DOM scan."""
        return WeakSet()

    @property
    def follows_tail(self) -> bool:
        return self.is_anchored and not self._anchor_released

    @property
    def can_jump_to_latest(self) -> bool:
        return not self.follows_tail

    def anchor(self, anchor: bool = True) -> None:
        changed = self.follows_tail != anchor
        if not self._restoring and changed:
            self.scroll_revision += 1
        if anchor:
            self._anchor_released = False
            # A reader cannot move a window they cannot see: a parked place stays.
            if self.shown:
                self.reader_position = self.reader_position.joined_tail()
        super().anchor(anchor)
        if changed:
            self.tail_follow_changed()

    def release_anchor(self) -> None:
        if not self.follows_tail:
            return
        if not self._restoring:
            self.scroll_revision += 1
        super().release_anchor()
        if not self._restoring and self.shown:
            self.reader_position = self.reader_position.left_tail(self)
        self.tail_follow_changed()

    def _check_anchor(self) -> None:
        """Native geometry checks cannot turn an offset reader into a tail reader."""

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        # Animation ticks and direct native scrolling change reader intent
        # too. The existing restoration scope excludes layout compensation.
        if new_value != old_value and not self._restoring:
            self.scroll_revision += 1
            if self.shown:
                self.reader_position = self.reader_position.moved(self, new_value - old_value)
            if self.lookahead.observe(new_value):
                self._schedule_settle()
            self.request_preparation()
        # Rejoin at the bottom after actual downward movement, including
        # keyboard, wheel and scrollbar input. Compensation uses the existing
        # restoration transaction and cannot choose a different reader policy.
        if (new_value > old_value and not self._restoring
                and all(not NEWER_END.visible_more(history) for history in self.histories)):
            # A lazy pager's mounted edge is not the source tail. Explicit End
            # still chooses follow through jump_to_latest; ordinary travel only
            # rejoins it once the current source has no unpublished newer rows.
            super()._check_anchor()
        self.tail_follow_changed()

    def _size_updated(self, size, virtual_size, container_size, layout=True) -> bool:
        # Native size commit owns scrollbar clamping. Compensate that movement
        # here, without treating unrelated Screen layouts as reader restoration.
        with self.layout_scroll():
            changed = super()._size_updated(size, virtual_size, container_size, layout)
        if changed:
            self.check_follow()
            self.request_preparation()
        return changed

    def check_follow(self) -> bool:
        if self.history_change is not None or not self.follows_tail:
            return False
        previous = self.scroll_y
        with self.layout_scroll():
            self.scroll_y = self.max_scroll_y
        return previous != self.scroll_y

    @property
    def history_mutation_root(self) -> Widget | None:
        """The subtree owned by the active native publication transaction.

        A direct native window lock still protects the whole window. Scoped
        history publications name their original mutation owner instead.
        """
        if not self.lock.is_locked:
            return None
        return self if self._history_mutation_root is None else self._history_mutation_root

    def visible_history_items(self, items):
        """Borrow this window's clipped cohort from the original native scene."""
        compositor = self.screen._compositor
        visible = compositor.published_widgets
        viewport = self.published_content_region
        if viewport is None:
            return
        for item in items:
            if item in visible:
                region, clip = visible[item]
                if (region.overlaps(viewport) and region.overlaps(clip)
                        and clip.overlaps(viewport)):
                    yield item

    @property
    def published_content_region(self):
        """This window's actual displayed content, independent of pending layout."""
        placement = self.screen._compositor._published_map.get(self)
        return None if placement is None else placement.content_region.intersection(placement.clip)

    @asynccontextmanager
    async def preserve_history(self, *, root: Widget | None = None):
        """Change what this window draws (inside `root`) with the reader kept on their row.

        The scope holds the window's tree lock for the change, then waits for
        the layout that shows it.
        """
        screen = self.screen
        async with AsyncExitStack() as shown:
            try:
                async with self.lock:
                    # Take the tree lock before joining a change already open:
                    # its layout cannot finish while this one holds the tree.
                    previous = self._history_mutation_root
                    mutation = self if root is None else root
                    if mutation is not self and self not in mutation.ancestors:
                        raise ValueError("History mutation must belong to its window")
                    if previous is not None:
                        if previous is mutation or previous in mutation.ancestors:
                            mutation = previous
                        elif mutation not in previous.ancestors:
                            mutation = Widget.get_common_ancestor(previous, mutation)
                    self._history_mutation_root = mutation
                    try:
                        await shown.enter_async_context(self._history_change())
                        yield
                    finally:
                        self._history_mutation_root = previous
            finally:
                # Held layout requests become actionable only after the outer
                # tree lock releases. Wake the screen before waiting for that layout.
                if not self.lock.is_locked:
                    screen.check_idle()

    @asynccontextmanager
    async def _history_change(self):
        """One change and the layout that shows it; a change inside another joins it.

        A body worker owns its own tree change and a nested pager may take
        history_lock while building that body, so this scope holds neither
        lock while it waits.
        """
        if self.history_change is not None:
            yield
            return
        screen = self.screen
        self.keep_reader()
        change = self.history_change = HistoryChange()
        geometry = self._geometry_revision
        drawn = False
        try:
            try:
                yield
            finally:
                # An unchanged page or already-live body needs no other layout.
                if self._geometry_revision != geometry:
                    change.request_layout(self)
            if self._geometry_revision == geometry:
                # No row moved: a position kept for this change is where the reader is.
                drawn = True
                return
            # Without waiting for the layout that places the reader, the next
            # change would start from rows that are not laid out yet.
            if self.is_attached and screen.is_current:
                await change.wait()
                drawn = change.laid_out
        finally:
            if self.history_change is change:
                self.history_change = None
                # The change is drawn, so the position has done its work and
                # the next change reads where the reader is then. One that no
                # layout has placed yet (a covered screen) stays kept.
                if drawn:
                    self.place_reader()
