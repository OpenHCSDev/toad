"""The history window: where its reader is, and keeping them there while the history changes."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from functools import cached_property, partial
from typing import TYPE_CHECKING
from weakref import WeakSet

from metaclass_registry.mro_dispatch import handles
from textual import events, on
from toad.client.line_blocks import Divider
from toad.reader_actions import LatestAction, PageDownAction, PageUpAction, ReaderAction
from toad.widget_actions import NativeMethodKeys
from textual.containers import VerticalScroll
from textual.geometry import Size
from textual.timer import Timer
from textual.widget import Widget

from toad.block_navigation import ConversationBlock
from toad.arrivals import AnimatesArrivals
from toad.history_jump import FollowsTail, JumpsToLatest, PagedReader
from toad.core.projection import MroProjection
from toad.no_worker import NO_TIMER, NoTimer
from toad.workspace_frame import WorkspaceHosted
from toad.widgets.message_row_owner import MessageRowOwner
from toad.widgets.presentation_window import Unplaced, arranged
from toad.client.history_pager import DirectionalPreparation, OffScreenRunway, PagingWindow, PresentationBudget, ReaderPlacement
from toad.client.history_changes import (
    HistoryChange,
    NO_HISTORY_CHANGE,
    NoHistoryChange,
    PageBelowTop,
    PageUnderTop,
    PinnedHeader,
    TopPage,
)

from toad.client.reader_position import (
    BlockPosition,
    FragmentPosition,
    ParkedPosition,
    ReaderPosition,
    TailPosition,
)


if TYPE_CHECKING:
    from toad.transcript_source_preparation import TranscriptSourcePreparation
    from toad.widgets.conversation import Contents
    from toad.widgets.transcript_history import FragmentSpan, TranscriptPageView




class HistoryWindow(FollowsTail, NativeMethodKeys, WorkspaceHosted, MroProjection[tuple[MessageRowOwner, ...]],
                    AnimatesArrivals, ReaderPlacement, PagedReader, VerticalScroll, PagingWindow,
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
    _restoring = False
    reader_position: ReaderPosition = TailPosition()
    """The position held during history changes and across tab returns."""
    # `scroll_revision`, `history_change` and `keep_reader` are JumpsToLatest's (shared with Qt).

    def action_scroll_end(self) -> None:
        self.jump_to_latest()

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
        if message.block.display and self.arrival_animation_visible:
            self.arrive((message.block,), glide_keys=())

    @cached_property
    def page_views(self) -> WeakSet[TranscriptPageView]:
        """Every transcript page mounted in this window; a page adds itself when it mounts."""
        return WeakSet()

    def park_reader(self, contents: Contents) -> ParkedPosition:
        """The reader's tab is being left: keep their place until its history is drawn again."""
        self.stop_arrival_motion()
        self.app.animator.force_stop_animation(self, "scroll_y", complete=False)
        self.scroll_target_y = self.scroll_y
        parked = self.reader_position.parked(self, contents)
        self.reader_position = parked
        return parked

    @property
    def animation_clock(self):
        return self.app.colours.clock

    @property
    def arrival_animation_visible(self) -> bool:
        return self.shown and self.app.app_focus

    def arrival_rows_height(self, keys: tuple[object, ...]) -> float | None:
        total = 0.0
        found = False
        for page in self.drawn_pages():
            for key in keys:
                slot = page._fragment_slots.get(key)
                if slot is not None:
                    total += slot.lines.height
                    found = True
        return total if found else None

    def repaint_arrival_keys(self, keys: tuple[object, ...]) -> None:
        wanted = set(keys)
        for page in self.drawn_pages():
            if any(key in page._fragment_slots for key in wanted):
                page.refresh()
        for block in tuple(self.live_blocks):
            if block in wanted:
                for widget in block.walk_children(with_self=True):
                    widget.repaint_lines()

    def prepare_history(self, history: TranscriptSourcePreparation) -> None:
        """A history about to be mounted loads the page ranges the kept position needs."""
        self.reader_position.prepare_history(history)
        if self.follows_tail:
            self.lookahead.destination(self.outer_size.height, pages_read=len(history.pages))

    def history_geometry_targets(self) -> tuple[Widget, ...]:
        """The widgets the kept position is measured from: layout places them even off screen."""
        return self.reader_for_layout().bodies(self)

    def shift_toolkit_travel(self, rows: float, destination: float) -> None:
        """A running scroll animation and its target move by the rows layout moved the reader."""
        self.app.animator.transform_running_animation(self, "scroll_y", lambda value: value + rows)
        self.scroll_target_y = destination + rows

    def retire_presentation_wait(self) -> None:
        """Release a change whose scene no longer promises another frame."""
        self.history_change.release()

    @on(events.Mount)
    def on_mount(self) -> None:
        self.screen.history_windows.add(self)
        self.request_preparation()

    @on(events.Unmount)
    def on_unmount(self) -> None:
        self.stop_arrival_motion()
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

    def toolkit_animated_travel(self) -> float:
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

    # `can_jump_to_latest` body (returns `not self.follows_tail`) is shared on JumpsToLatest.

    def apply_anchor(self, anchor: bool) -> None:
        if anchor:
            # Tail intent replaces earlier motion even while a publication has
            # no scrollable rows. Native cancellation depends on the scrollbar.
            self.cancel_head_reveal()
            self.app.animator.force_stop_animation(self, "scroll_y", complete=False)
            self.scroll_target_y = self.scroll_y
            self._anchor_released = False
        # Textual's own anchor: the next one after the shared step in this window's MRO.
        super(FollowsTail, self).anchor(anchor)

    def end_travel(self) -> None:
        self.scroll_target_y = self.scroll_y

    @property
    def tail_scroll_y(self) -> float:
        return float(self.max_scroll_y)

    @property
    def content_top(self) -> int:
        return self.scrollable_content_region.y

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        # Animation ticks and direct native scrolling change reader intent
        # too. The existing restoration scope excludes layout compensation.
        if new_value != old_value and not self._restoring:
            if not self._applying_head_reveal:
                self.cancel_head_reveal()
            self.record_reader_scroll(new_value - old_value)
            self._invalidate_tooltip_on_scroll()
        else:
            self.rejoin_reached_tail()
        # Shared post-anchor response; `JumpsToLatest.respond_to_scroll` gates settle on
        # travel so an idle tick doesn't restart the timer or re-queue preparation.
        self.respond_to_scroll(new_value)

    def _invalidate_tooltip_on_scroll(self) -> None:
        """Scrolling moves the row under the mouse without a mouse event. Textual pins the
        tooltip at the mouse position it saw when the hover timer fired (screen.py:2016),
        so after a scroll the shown tooltip belongs to a row that has moved on. Clear it
        when the tooltip is showing a descendant of this viewport; the next hover re-draws
        fresh content for the row now under the mouse."""
        screen = self.screen
        tip_widget = screen._tooltip_widget
        if tip_widget is None:
            return
        for ancestor in tip_widget.walk_ancestors():
            if ancestor is self:
                screen._clear_tooltip()
                return

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
    async def tree_change(self):
        """This window's tree lock for the change. Layout requests held under it become
        actionable only once it releases, so the screen is woken then, before the change
        waits for that layout."""
        screen = self.screen
        try:
            async with self.lock:
                yield
        finally:
            if not self.lock.is_locked:
                screen.check_idle()

    @property
    def geometry_revision(self) -> int:
        return self._geometry_revision
