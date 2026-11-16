"""The history window: where its reader is, and keeping them there while the history changes."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from functools import cached_property, partial
from typing import TYPE_CHECKING
from weakref import WeakSet

from metaclass_registry.mro_dispatch import handles
from textual import events, on
from textual.widgets.text_area import VimMode
from toad.widget_actions import Action, NativeMethodKeys
from textual.containers import VerticalScroll
from textual.geometry import Size
from textual.timer import Timer
from textual.widget import Widget

from toad.block_navigation import ConversationBlock
from toad.frame_presentation import FollowsUnrisenRows, UnrisenRows
from toad.history_jump import JumpsToLatest
from toad.core.projection import MroProjection
from toad.no_worker import NO_TIMER, NoTimer
from toad.widget_view import WorkspaceHosted
from toad.widgets.message_row_owner import MessageRowOwner
from toad.client.history_preparation import NEWER_END
from toad.widgets.presentation_window import Unplaced, arranged
from toad.client.history_pager import DirectionalPreparation, OffScreenRunway, PagingWindow, PresentationBudget, ReaderPlacement

from toad.client.reader_position import (
    BlockPosition,
    FragmentPosition,
    ParkedPosition,
    ReaderPosition,
    TailPosition,
    UNSHOWN_READER,
)


if TYPE_CHECKING:
    from toad.client.line_blocks import Divider
    from toad.transcript_source_preparation import TranscriptSourcePreparation
    from toad.widgets.conversation import Contents
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


class ReaderAction(Action, affix="Action"):
    """Vim reader keys every history window answers."""


class PageDownAction(ReaderAction, declared_name="reader_page_down"):
    """Move the reader one page toward the latest message."""

    keys = {VimMode: ("ctrl+d",)}

    def apply(self, window: HistoryWindow) -> None:
        window.action_page_down()


class PageUpAction(ReaderAction, declared_name="reader_page_up"):
    """Move the reader one page toward older history."""

    keys = {VimMode: ("ctrl+u",)}

    def apply(self, window: HistoryWindow) -> None:
        window.action_page_up()


class LatestAction(ReaderAction):
    """Follow the source tail, including pages outside the mounted window."""

    keys = {VimMode: ("G",)}

    def apply(self, window: HistoryWindow) -> None:
        window.jump_to_latest()


class HistoryWindow(NativeMethodKeys, WorkspaceHosted, MroProjection[tuple[MessageRowOwner, ...]],
                    ReaderPlacement, JumpsToLatest, FollowsUnrisenRows, VerticalScroll, PagingWindow,
                    actions=(ReaderAction,)):
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
            # A move that leaves the reader at the end (ctrl+d at the bottom moves nothing,
            # so no scroll change reports it) still reads the tail once it settles.
            self.call_after_refresh(self.rejoin_reached_tail)

    def action_scroll_up(self) -> None:
        self._scroll_or_prepare(-1, super().action_scroll_up)

    def action_scroll_down(self) -> None:
        self._scroll_or_prepare(1, super().action_scroll_down)

    @on(events.MouseScrollUp)
    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.prevent_default()
        self._scroll_or_prepare(-self.app.scroll_sensitivity_y, super()._on_mouse_scroll_up, event)
        event.stop()

    def action_page_up(self) -> None:
        self._scroll_or_prepare(-max(1, self.scrollable_content_region.height), super().action_page_up)

    @on(events.MouseScrollDown)
    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.prevent_default()
        self._scroll_or_prepare(self.app.scroll_sensitivity_y, super()._on_mouse_scroll_down, event)
        event.stop()

    def action_page_down(self) -> None:
        self._scroll_or_prepare(max(1, self.scrollable_content_region.height), super().action_page_down)

    def scroll_page_fraction(self, direction: int, divisor: int) -> None:
        distance = direction * max(1, self.scrollable_content_region.height // divisor)
        # One update per press: a held key replaces each glide half-way, so animating only adds
        # frames that move scroll_y and run layout (140 frames for 60 held presses, measured).
        self._scroll_or_prepare(distance, partial(self.scroll_relative, None, distance, animate=False))

    @on(events.MouseScrollLeft)
    def _on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        event.prevent_default()
        super()._on_mouse_scroll_left(event)
        event.stop()

    @on(events.MouseScrollRight)
    def _on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        event.prevent_default()
        super()._on_mouse_scroll_right(event)
        event.stop()

    CACHE_SUBTREE_GEOMETRY = True
    scroll_revision = 0
    _restoring = False
    reader_position: ReaderPosition = TailPosition()
    """The position held during history changes and across tab returns."""
    history_change: HistoryChange | NoHistoryChange = NO_HISTORY_CHANGE

    def action_scroll_end(self) -> None:
        self.jump_to_latest()

    def tail_follow_changed(self) -> None:
        """Project the canonical tail-follow state in a specialized window."""

    @property
    def shown(self) -> bool:
        """Whether layout draws this window: its screen is the current one and nothing above it is hidden."""
        return self.is_attached and self.screen.is_current and all(node.display for node in self.ancestors_with_self)

    def displays(self, widget: Widget) -> bool:
        """Whether a widget inside this window is displayed, with everything between them."""
        chain = widget.ancestors_with_self
        return self in chain and all(node.display for node in chain[:chain.index(self)])

    def holds(self, item: Widget) -> bool:
        return item.is_attached and self.displays(item)

    def placed_live_blocks(self) -> Iterator[tuple[Widget, int]]:
        """Candidates come from the published frame but are measured in the layout just made,
        so a block published last frame and not placed now is no candidate. Containers of
        other blocks do not hold the reader."""
        published = self.screen._compositor.published_widgets
        blocks = [block for block in self.live_blocks if block in published]
        holders = {ancestor for block in blocks for ancestor in block.ancestors}
        return self.placements(self.visible_history_items(block for block in blocks if block not in holders))

    def after_source_presented(self, callback, *arguments) -> None:
        self.call_after_refresh(callback, *arguments)

    def request_reader_layout(self) -> None:
        self.refresh(layout=True)

    def placements[Placed: Widget](self, widgets: Iterable[Placed]) -> Iterator[tuple[Placed, int]]:
        """Each widget the last layout placed, with its first row in this window's content.

        Viewport layout places what is on screen plus the screen's declared
        geometry targets; a widget off screen is not yielded.
        """
        return self.placed_in(self.screen._compositor._layout_map, widgets)

    def placed_in[Placed: Widget](
        self, geometry: object, widgets: Iterable[Placed]
    ) -> Iterator[tuple[Placed, int]]:
        """One reading of a geometry map, from whichever map the caller means.

        A caller that remembers an answer must remember which geometry answered it: the
        current layout map is replaced by a prepared layout before it is published, so
        reading that map while keying on the published one labels an answer with a map
        that did not supply it.
        """
        for widget in widgets:
            chain = widget.ancestors_with_self
            path = chain[:chain.index(self)] if self in chain else chain
            if all(node in geometry for node in path):
                yield widget, sum(geometry[node].virtual_region.y for node in path)

    def row_of(self, widget: Widget) -> int:
        """The row of a widget layout must have placed: one on screen, or one the kept position names."""
        for _, row in self.placements((widget,)):
            return row
        raise LookupError(f"{widget!r} is not placed in {self!r}'s layout; "
                          "a reader position's widgets must be visible or declared geometry targets")

    @handles(Widget)
    def native_message_rows(self, widget: Widget) -> tuple[MessageRowOwner, ...]:
        """A native widget supplies no live message unless it declares that capability."""
        return ()

    @handles(MessageRowOwner)
    def live_message_row(self, message: MessageRowOwner) -> tuple[MessageRowOwner, ...]:
        return (message,)

    def top_message_header(self) -> PinnedHeader:
        """The header of the message drawn on the window's top row, when that header is scrolled
        above it, with the column the flow draws it in."""
        return self.top_page().pinned_header(self)

    def live_message_header(self) -> PinnedHeader:
        """The header of the live message drawn on the window's top row, or none."""
        y = self.scroll_y
        messages = (message
                    for widget in self.visible_history_items(self.screen._compositor.published_widgets)
                    for message in self.project_value(widget))
        for message, first in self.placements(messages):
            if first <= y < first + message.outer_size.height:
                return PinnedHeader(message.sticky_header(int(y - first)),
                                    message.content_region.x - self.content_region.x,
                                    message.size.width)
        return PinnedHeader((), 0, 0)

    _placed_pages: tuple[tuple[tuple[TranscriptPageView, int], ...], object] = ((), None)
    """The last published placement of this window's drawn pages, and the map it came from."""

    def placed_pages(self) -> tuple[tuple[TranscriptPageView, int], ...]:
        """The drawn pages and their first rows, as the published geometry placed them.

        Keyed on the published map itself, which is the publication: the compositor
        replaces it only with an actual writer update and drops its published widgets in
        the same breath (`_compositor.py:669`). So this cannot answer for a frame that has
        been replaced, and it needs no expiry of its own.

        Scrolling moves `scroll_y` and nothing here: a page's first row is layout-space,
        and which pages are drawn comes from the published frame. Rebuilding this per
        scroll tick cost 1.005s of a 31s phone trace in `top_message_header`, each tick
        allocating an ancestor chain per page and walking the layout map for it.
        """
        published = self.screen._compositor._published_map
        placed, against = self._placed_pages
        if against is not published:
            placed = tuple(self.placed_in(published, self.drawn_pages()))
            self._placed_pages = (placed, published)
        return placed

    def top_page(self) -> TopPage:
        """The drawn page under the window's top row, else the nearest one below it, else none."""
        y = self.scroll_y
        return min(((PageUnderTop if first <= y else PageBelowTop)(page, first)
                    for page, first in self.placed_pages()
                    if page.line_count and first + page.line_count > y),
                   key=lambda placed: max(y, placed.first), default=TopPage())

    def drawn_pages(self):
        """Pages in this window's published viewport, not all loaded history."""
        published = self.screen._compositor.published_widgets
        pages = (page for page in self.page_views if page in published)
        return (page for page in self.visible_history_items(pages) if self.displays(page))

    @cached_property
    def live_blocks(self) -> WeakSet[Widget]:
        """Every live block mounted inside this window; each announces itself when it mounts."""
        return WeakSet()

    @on(ConversationBlock.Mounted)
    def on_conversation_block_mounted(self, message: ConversationBlock.Mounted) -> None:
        message.stop()
        self.live_blocks.add(message.block)

    @cached_property
    def page_views(self) -> WeakSet[TranscriptPageView]:
        """Every transcript page mounted in this window; a page adds itself when it mounts."""
        return WeakSet()

    def keep_reader(self) -> None:
        """What this window draws is about to change: layout keeps the reader where they are now."""
        self.screen.reader_kept(self)

    def park_reader(self, contents: Contents) -> ParkedPosition:
        """The reader's tab is being left: keep their place until its history is drawn again."""
        self.app.animator.force_stop_animation(self, "scroll_y", complete=False)
        self.scroll_target_y = self.scroll_y
        parked = self.reader_position.parked(self, contents)
        self.reader_position = parked
        return parked

    def prepare_history(self, history: TranscriptSourcePreparation) -> None:
        """A history about to be mounted loads the page ranges the kept position needs."""
        self.reader_position.prepare_history(history)
        if self.follows_tail:
            self.lookahead.destination(self.outer_size.height, pages_read=len(history.pages))

    def history_geometry_targets(self) -> tuple[Widget, ...]:
        """The widgets the kept position is measured from: layout places them even off screen."""
        return self.reader_for_layout().bodies(self)

    def reader_for_layout(self) -> ReaderPosition:
        """The kept position as this layout can place it; a window the layout does not draw places none."""
        if not self.shown:
            return UNSHOWN_READER
        self.reader_position = self.reader_position.for_layout(self, self.reader_position)
        return self.reader_position

    def place_layout_reader(self) -> bool:
        """After a layout: put the reader back on the kept position; True when that scrolled."""
        return self.reader_for_layout().placed_by_layout(self)

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

    def retire_presentation_wait(self) -> None:
        """Release a change whose scene no longer promises another frame."""
        self.history_change.release()

    @on(events.Mount)
    def on_mount(self) -> None:
        self.screen.history_windows.add(self)
        self.request_preparation()

    @on(events.Unmount)
    def on_unmount(self) -> None:
        self.retire_presentation_wait()
        self.settle_preparation()
        self.screen.history_windows.discard(self)

    def prepare_viewport(self) -> None:
        """Window subclasses publish work that depends on committed geometry."""

    @cached_property
    def presentation_budget(self) -> PresentationBudget:
        return PresentationBudget(buffer_viewports=self.settings.ui.history_buffer_viewports)

    @cached_property
    def lookahead(self) -> DirectionalPreparation:
        """Measured scroll travel; it sizes how far ahead histories prepare."""
        return DirectionalPreparation(self)

    def runway(self, history) -> OffScreenRunway:
        return arranged(history).runway(arranged(self))

    @property
    def animated_travel(self) -> float:
        return self.scroll_target_y - self.scroll_y if self.app.animator.is_being_animated(self, "scroll_y") else 0

    @property
    def viewport_rows(self) -> int:
        return self.outer_size.height

    @property
    def content_rows(self) -> int:
        return self.scrollable_content_region.height

    @property
    def unfilled_rows(self) -> int:
        # Native virtual size includes the viewport's blank alignment space.
        # Flowing placements retain the actual occupied extent, excluding
        # overlays and docks.
        viewport = self.scrollable_size
        return viewport.height - self.arrange(viewport).flow_bounds.height

    @property
    def presenting(self) -> bool:
        return self.screen.is_active

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

    # Stopping a fired Textual timer does nothing, so the last one set is kept.
    _settle_timer: Timer | NoTimer = NO_TIMER

    def _schedule_settle(self) -> None:
        self._settle_timer.stop()
        self._settle_timer = self.set_timer(self.lookahead.idle_seconds, self._settle)

    def settle_preparation(self) -> None:
        """A hidden or closing window stops predicting travel."""
        self._settle_timer.stop()
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
            # Tail intent replaces earlier motion even while a publication has
            # no scrollable rows. Native cancellation depends on the scrollbar.
            self.app.animator.force_stop_animation(self, "scroll_y", complete=False)
            self.scroll_target_y = self.scroll_y
            self._anchor_released = False
            # A reader cannot move a window they cannot see: a parked place stays.
            if self.shown:
                self.reader_position = self.reader_position.joined_tail()
        super().anchor(anchor)
        if not anchor and self.shown and not self._restoring:
            self.reader_position = self.reader_position.left_tail(self)
        if changed:
            self.tail_follow_changed()

    def release_anchor(self) -> None:
        if not self.follows_tail:
            return
        self.scroll_target_y = self.scroll_y
        # Stop native following, rather than leaving a released native anchor
        # which can silently rejoin at a mounted page edge.
        self.anchor(False)

    @property
    def row_holders(self) -> tuple[UnrisenRows, ...]:
        """What this window subtracts from its followed tail: the pagers drawing saved pages.

        A live block cascades too and answers `unrevealed_rows` for itself, and it is not in
        this sum. Holding the tail above unrisen rows means scrolling *up*, and scrolling up
        is how this window asks for older history: with a live block in the sum, a
        128-paragraph answer kept loading pages behind itself and never settled
        (test_transcript_presentation_fencing, which stalls on exactly that, both with the
        reader driven per frame and without).

        Doing it for a live block therefore means the block withholding the height of its
        unrisen rows, so the end of the document is where the risen rows end and nobody
        scrolls anywhere. That is a change to what a growing block reports as its height,
        and that test is its guard.
        """
        return tuple(self.histories)

    def rows_revealed(self) -> None:
        """A frame of a cascade inside this window: the reader goes down with the rows."""
        self.reader_position.revealed(self)

    @property
    def tail_scroll_y(self) -> float:
        """The followed tail: the end, less the arriving rows that have not risen yet, and
        never more than one window above it.

        A reader held back further than fills the window is off the arrival entirely, and
        the count can exceed the whole scroll range while a layout is in flight: a live
        block reports its rows as soon as layout gives it a height, before the document it
        sits in has grown to hold them. Subtracting that unclamped put the reader at the top
        of the history mid-layout, which is both wrong and a scroll the layout then has to
        answer (test_transcript_presentation_fencing stalled on it).
        """
        held = min(sum(holder.unrevealed_rows() for holder in self.row_holders),
                   self.scrollable_content_region.height)
        return max(0, self.max_scroll_y - held)

    def message_too_tall(self, height: int) -> bool:
        """A message taller than the viewport needs its head placed; a short one stays put."""
        return height > self.scrollable_content_region.height

    def message_head_hidden(self, height: int, head_y: int) -> bool:
        """A tall message whose head row is above the viewport needs its head placed."""
        return self.message_too_tall(height) and head_y < self.scrollable_content_region.y

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
        self.rejoin_reached_tail()
        self.tail_follow_changed()

    def rejoin_reached_tail(self) -> None:
        """A reader at the end of the source tail follows it again, through the same owner as
        explicit tail selection. Being at the end is geometry, not a scroll: asked only when
        scroll_y changed, a page down at the bottom (released, moved nothing) or a tool
        collapsing under the reader left "Back to bottom" showing at the bottom."""
        if (not self._restoring and not self.follows_tail
                and self.scroll_y >= self.max_scroll_y
                and all(not NEWER_END.visible_more(history) for history in self.histories)):
            self.anchor(True)

    def _size_updated(self, size: Size, virtual_size: Size, container_size: Size, layout: bool=True) -> bool:
        # Native size commit owns scrollbar clamping. Compensate that movement
        # here, without treating unrelated Screen layouts as reader restoration.
        with self.layout_scroll():
            changed = super()._size_updated(size, virtual_size, container_size, layout)
        if changed:
            self.check_follow()
            # Geometry can put a reader at the end without a scroll of theirs: a tool
            # collapsing below them clamps them there inside layout_scroll.
            self.rejoin_reached_tail()
            self.request_preparation()
        return changed

    def check_follow(self) -> bool:
        return self.history_change.check_follow(self)

    def visible_history_items(self, items: Iterable[Widget]):
        """Borrow this window's clipped cohort from the original native scene."""
        compositor = self.screen._compositor
        visible = compositor.published_widgets
        viewport = self.published_viewport
        for item in items:
            if item in visible and viewport.shows(*visible[item]):
                yield item

    @property
    def published_viewport(self) -> Unplaced:
        """This window's actual displayed content, independent of pending layout."""
        return Unplaced.found(self.screen._compositor._published_map.get(self),
                              lambda placement: placement.content_region.intersection(placement.clip))

    def show_rows(self, rows: range) -> None:
        """Scroll just far enough that these content rows are on screen, the first before the last."""
        top, height = int(self.scroll_y), self.scrollable_content_region.height
        if rows.start < top:
            destination = rows.start
        elif rows.stop > top + height:
            destination = min(rows.start, rows.stop - height)
        else:
            return
        self.release_anchor()
        self.scroll_to(y=destination, animate=False, immediate=True)

    @asynccontextmanager
    async def preserve_history(self):
        """Change what this window draws with the reader kept on their row.

        The scope holds the window's tree lock for the change, then waits for
        the layout that shows it.
        """
        screen = self.screen
        async with AsyncExitStack() as shown:
            try:
                async with self.lock:
                    # Take the tree lock before joining a change already open:
                    # its layout cannot finish while this one holds the tree.
                    await shown.enter_async_context(self._history_change())
                    yield
            finally:
                # Held layout requests become actionable only after the outer
                # tree lock releases. Wake the screen before waiting for that layout.
                if not self.lock.is_locked:
                    screen.check_idle()

    def _history_change(self):
        """One change and the layout that shows it; a change inside another joins it."""
        return self.history_change.opened(self)
