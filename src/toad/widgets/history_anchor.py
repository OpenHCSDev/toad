"""Stable scroll anchoring shared by both saved and IRC history paging."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
import asyncio
from typing import TYPE_CHECKING, ClassVar
from weakref import WeakSet

from textual.widget import Widget
from textual import events
from textual.containers import VerticalScroll
from toad.widgets.presentation_window import DirectionalPreparation, PresentationBudget
from toad.widgets.presentation_window import protected_presentations

if TYPE_CHECKING:
    from toad.widgets.tool_call import ToolCall
    from toad.transcript_preparation import TranscriptPageAdmission
    from toad.transcript_source_preparation import TranscriptSourcePreparation
    from toad.widgets.transcript_fragments import TranscriptFragment


class WindowPosition(ABC):
    """Apply an owned layout intent without recording another user scroll."""

    def required_bodies(self, window: "HistoryWindow") -> tuple[Widget, ...]:
        """The original intent supplies its preparation and placement roots."""
        return ()

    def before_layout(self, window: "HistoryWindow") -> "WindowPosition":
        return self

    def current(self, window: "HistoryWindow") -> bool:
        return True

    def restore(self, window: "HistoryWindow") -> bool:
        if not self.current(window):
            return False
        with self.geometry(window):
            return self._restore(window)

    @classmethod
    @contextmanager
    def geometry(cls, window: "HistoryWindow"):
        """Own native reflow and its compensation as one reader restoration."""
        restoring = window._restoring
        previous = window.scroll_y
        destination = window.scroll_target_y
        window._restoring = True
        try:
            yield
        finally:
            try:
                if not restoring:
                    compensation = window.scroll_y - previous
                    cls._translate_motion(window, destination, compensation)
                    window.lookahead.relocated(compensation)
            finally:
                window._restoring = restoring

    @staticmethod
    def _translate_motion(window: "HistoryWindow", destination: float, compensation: float) -> None:
        if compensation:
            window.app.animator.transform_running_animation(
                window, "scroll_y", lambda value: value + compensation,
            )
            window.scroll_target_y = destination + compensation

    @abstractmethod
    def _restore(self, window: "HistoryWindow") -> bool: ...


@dataclass(eq=False)
class WindowRestoration:
    """An acquired compensation lifetime, with or without a reading position."""

    position: WindowPosition | None
    layout_ready: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    layout_requests: int = field(default=0, init=False)
    """How many layouts this restoration has requested; a layout answers those made before it started."""

    def required_bodies(self, window: "HistoryWindow") -> tuple[Widget, ...]:
        return () if self.position is None else self.position.required_bodies(window)

    def prepare_layout(self, window: "HistoryWindow") -> WindowPosition | None:
        position = self.position
        if position is not None and all(body.is_attached for body in position.required_bodies(window)):
            self.position = position.before_layout(window)
            return self.position
        return None

    def restore_layout(self, window: "HistoryWindow", position: WindowPosition) -> bool:
        previous = window.scroll_y
        position.restore(window)
        # A held layout can clamp scroll before publishing the new source
        # position. Keep the actual intent until this acquisition ends.
        self.position = position
        return window.scroll_y != previous

    def request_layout(self, window: "HistoryWindow") -> None:
        # Layouts during the mutation do not complete its final compensation.
        # Arm the same acquired event before making that layout actionable.
        self.layout_requests += 1
        self.layout_ready.clear()
        window.refresh(layout=True)

    def finish_layout(self, answered: int) -> None:
        """A layout that started after `answered` requests has finished.

        A layout running over loop turns may finish after a request made while
        it ran; that request waits for the layout that places it.
        """
        if answered == self.layout_requests:
            self.layout_ready.set()

    def release(self) -> None:
        """No layout will answer: release the waiter."""
        self.layout_ready.set()

    async def wait(self) -> None:
        await self.layout_ready.wait()


class ReaderPosition(WindowPosition):
    """Source-owned reader intent, independent of retired widget geometry."""

    admissions: tuple["TranscriptPageAdmission", ...] = ()

    @staticmethod
    def _translate_motion(window: "HistoryWindow", destination: float, compensation: float) -> None:
        """Explicit native navigation owns its new destination, not the old curve."""

    @classmethod
    def capture(cls, window: "HistoryWindow") -> "ReaderPosition":
        # Follow intent enters from Textual's native scroll boundary once.
        if window.follows_tail:
            return TailReaderPosition()
        # Parked pagers revoke source work and leave window.histories while
        # their original admitted pages remain in the native tree. Capture
        # those page ranges before eviction, including the parked resource.
        histories = tuple(window.transcript_histories())
        admissions = tuple(
            admission for history in histories
            for admission in history.capture_reader_admissions()
        )
        for history in histories:
            for page in history.pages:
                # The reader's row is on screen: an unplaced page cannot hold it.
                if (offset := HistoryAnchor._placed_offset(page, window)) is None:
                    continue
                # Above this page (on the earlier-history edge), keep the
                # reader's distance from the page's first row.
                above = min(0, int(window.scroll_y - offset))
                row = int(window.scroll_y - offset) - above
                if row < page.line_count and (found := page.fragment_at(row)) is not None:
                    fragment, within = found
                    return FragmentReaderPosition(fragment, within + above, admissions)
        return OffsetReaderPosition(window.scroll_y, admissions)

    def prepare_history(self, history: "TranscriptSourcePreparation") -> None:
        """Restore admitted source ranges; tail readers have no older admission."""
        history.restore_reader_admissions(self.admissions)

    @staticmethod
    def _restore_row(window: "HistoryWindow", destination: float | None) -> bool:
        window.release_anchor()
        if destination is None:
            return False
        window.scroll_to(y=destination, animate=False, immediate=True)
        # A provisional native extent may clamp the request. Only attaining
        # the original reading row completes this owner's restoration.
        return window.scroll_y == destination


@dataclass(frozen=True)
class TailReaderPosition(ReaderPosition):
    def _restore(self, window: "HistoryWindow") -> bool:
        window.anchor()
        return True


@dataclass(frozen=True)
class OffsetReaderPosition(ReaderPosition):
    y: float
    admissions: tuple["TranscriptPageAdmission", ...]

    def _restore(self, window: "HistoryWindow") -> bool:
        return self._restore_row(window, self.y)


@dataclass(frozen=True)
class FragmentReaderPosition(ReaderPosition):
    """Original source record and its reading row, independent of preceding rows.

    The source resource survives native eviction. No old widget, descendant
    path or reconstructed content is retained to find its new presentation.
    """

    fragment: TranscriptFragment
    offset: float
    admissions: tuple["TranscriptPageAdmission", ...]

    def record(self, window: "HistoryWindow"):
        """The page that draws this fragment, if it is admitted."""
        return next((page for history in window.transcript_histories() for page in history.pages
                     if page.fragment_line(self.fragment) is not None), None)

    def current(self, window: "HistoryWindow") -> bool:
        record = self.record(window)
        return record is not None and record.display

    def required_bodies(self, window: "HistoryWindow") -> tuple[Widget, ...]:
        record = self.record(window)
        return () if record is None else (record,)

    def placement(self, window: "HistoryWindow") -> int | None:
        record = self.record(window)
        if record is None:
            return None
        # The record is a declared geometry target, so layout placed it.
        return HistoryAnchor._offset(record, window) + record.fragment_line(self.fragment)

    def _restore(self, window: "HistoryWindow") -> bool:
        placed = self.placement(window)
        return self._restore_row(window, None if placed is None else placed + self.offset)


class HistoryWindow(VerticalScroll):
    """A document owns reader intent and ends its pointer-scroll route.

    Nested controls receive the native event first. Once it reaches this
    viewport, moving or clamping completes it; workspace ancestors cannot
    scroll this document and must not hold its input at a reached boundary.
    """

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.prevent_default()
        super()._on_mouse_scroll_up(event)
        event.stop()

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.prevent_default()
        super()._on_mouse_scroll_down(event)
        event.stop()

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
    history_restoration: WindowRestoration | None = None
    _history_mutation_root: Widget | None = None

    def action_scroll_end(self) -> None:
        self.jump_to_latest()

    def jump_to_latest(self) -> None:
        """Follow the source tail, including pages outside the mounted window."""
        self.anchor()
        self.destination()
        for history in tuple(self.histories):
            if history.has_newer:
                history.request_latest()

    @property
    def pending_reader_position(self) -> ReaderPosition | None:
        """A source-owning window lends its actual pending restoration."""
        return None

    @property
    def reader_bodies(self) -> tuple[Widget, ...]:
        position = self.pending_reader_position
        return () if position is None else position.required_bodies(self)

    def history_geometry_targets(self) -> tuple[Widget, ...]:
        restoration = self.history_restoration
        return tuple(dict.fromkeys((*self.reader_bodies,
                                    *(restoration.required_bodies(self)
                                      if restoration is not None else ()))))

    def retire_presentation_wait(self) -> None:
        """Release a transaction whose scene no longer promises another frame."""
        if (restoration := self.history_restoration) is not None:
            restoration.release()

    def on_mount(self) -> None:
        from toad.screens.workspace import WorkspaceScreen

        if isinstance(screen := self.screen, WorkspaceScreen):
            screen.history_windows.add(self)
        self.request_preparation()

    def on_viewport_layout(self, _screen) -> None:
        self.request_preparation()

    def prepare_viewport(self) -> None:
        """Native publication, rather than raw motion, owns visible tools."""
        self.hydrate_visible_tools()

    def on_unmount(self) -> None:
        from toad.screens.workspace import WorkspaceScreen

        self.retire_presentation_wait()
        self.settle_preparation()
        if isinstance(screen := self.screen, WorkspaceScreen):
            screen.history_windows.discard(self)

    @cached_property
    def presentation_budget(self) -> PresentationBudget:
        return PresentationBudget(buffer_viewports=self.app.settings.ui.history_buffer_viewports)

    @cached_property
    def lookahead(self) -> DirectionalPreparation:
        """Measured scroll travel; it sizes how far ahead histories prepare."""
        return DirectionalPreparation(self)

    @property
    def rows_per_fragment(self) -> float:
        """Average drawn rows per admitted fragment, for converting rows to fragments."""
        pages = [page for history in self.histories for page in history.pages if page.line_count]
        fragments = sum(page.stop - page.start for page in pages)
        return sum(page.line_count for page in pages) / fragments if fragments else max(1, self.outer_size.height)

    def request_preparation(self) -> None:
        """Histories prepare around the reader after the next published frame."""
        if not self.is_attached or self._closing:
            return
        for history in tuple(self.histories):
            history.request_preparation()
        self.screen.frame_presentation.defer(self, self.prepare_viewport)

    def destination(self) -> None:
        """End: prepare the destination in one burst, not every page between."""
        self.lookahead.observe(self.scroll_y)
        self.lookahead.destination(self.outer_size.height)
        self._schedule_settle()
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

    @cached_property
    def pending_tool_content(self) -> WeakSet[ToolCall]:
        """Only off-screen autoexpanded outputs need a visibility check."""
        return WeakSet()

    def hydrate_visible_tools(self, _position: float = 0) -> None:
        if not self.pending_tool_content or self.screen is not self.app.screen:
            return
        for tool in tuple(self.pending_tool_content):
            tool.hydrate_if_visible()

    @property
    def follows_tail(self) -> bool:
        return self.is_anchored and not self._anchor_released

    def anchor(self, anchor: bool = True) -> None:
        if not self._restoring:
            self.scroll_revision += 1
        if anchor:
            self._anchor_released = False
        super().anchor(anchor)

    def release_anchor(self) -> None:
        if not self._restoring:
            self.scroll_revision += 1
        super().release_anchor()

    def _check_anchor(self) -> None:
        """Native geometry checks cannot turn an offset reader into a tail reader."""

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        # Animation ticks and direct native scrolling change reader intent
        # too. The existing restoration scope excludes layout compensation.
        if new_value != old_value and not self._restoring:
            self.scroll_revision += 1
            if self.lookahead.observe(new_value):
                self._schedule_settle()
            self.request_preparation()
        # Rejoin at the bottom after actual downward movement, including
        # keyboard, wheel and scrollbar input. Compensation uses the existing
        # restoration transaction and cannot choose a different reader policy.
        if (new_value > old_value and not self._restoring
                and all(not history.has_newer for history in self.histories)):
            # A lazy pager's mounted edge is not the source tail. Explicit End
            # still chooses follow through jump_to_latest; ordinary travel only
            # rejoins it once the current source has no unpublished newer rows.
            super()._check_anchor()

    def _size_updated(self, size, virtual_size, container_size, layout=True) -> bool:
        # Native size commit owns scrollbar clamping. Compensate that movement
        # here, without treating unrelated Screen layouts as reader restoration.
        with WindowPosition.geometry(self):
            changed = super()._size_updated(size, virtual_size, container_size, layout)
        if changed:
            self.check_follow()
            self.request_preparation()
        return changed

    def check_follow(self) -> bool:
        if self.history_restoration is not None or not self.follows_tail:
            return False
        previous = self.scroll_y
        with WindowPosition.geometry(self):
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

    def transcript_histories(self):
        """Read original pager custody without walking rich native descendants."""
        from toad.widgets.transcript_history import TranscriptHistory

        pending = list(reversed(self.children))
        while pending:
            node = pending.pop()
            if isinstance(node, TranscriptHistory):
                yield node
                if (projection := node.filter.state.overlay) is not None:
                    pending.append(projection)
            else:
                pending.extend(reversed(node.children))

    def reader_anchor(self) -> Widget | None:
        """What the reader is looking at: extent changes preserve it.

        A tail reader anchors to the window itself. Otherwise it is the
        topmost displayed message, or None when nothing is displayed and there
        is no reading position to keep.
        """
        if self.history_restoration is not None:
            roots = self.history_restoration.required_bodies(self)
            if roots:
                return roots[0]
        if self.follows_tail:
            return self
        from toad.block_navigation import ConversationBlock
        from toad.widgets.transcript_history import TranscriptHistory, TranscriptPageView

        # The topmost visible message: a line-drawn page or a live block.
        visible = self.screen._compositor.published_widgets
        candidates = (*self.query(TranscriptPageView), *(
            block for block in self.query(ConversationBlock) if not isinstance(block, TranscriptHistory)))
        return min(self.visible_history_items(candidates),
                   key=lambda node: visible[node][0].y, default=None)

    def protect_history(self, items, *, older: bool) -> tuple[Widget | None, set[Widget]]:
        """Keep the reader's painted records and interaction owners during paging.

        Source leaves supply their mounted presentations, not another copy of
        the scene. Both native and wire pages borrow this one published geometry
        and the window's original selection/focus before admitting or trimming.
        """
        items = tuple(items)
        retained = tuple(self.visible_history_items(items))
        # Rows the reader can see anchor the change; otherwise the reader is
        # elsewhere and that position is kept instead.
        anchor = retained[0 if older else -1] if retained else self.reader_anchor()
        protected = protected_presentations(items, self.screen._interaction_widgets())
        protected.update(retained)
        if anchor is not None:
            protected.add(anchor)
        return anchor, protected

    @asynccontextmanager
    async def preserve_history(self, widget: Widget | None, *, root: Widget | None = None,
                               position: WindowPosition | None = None):
        """Fence a native source mutation inside its reader layout lifetime."""
        screen = self.screen
        async with AsyncExitStack() as reader:
            try:
                async with self.lock:
                    # Acquire the native mutation before borrowing an outstanding
                    # anchor. Its owner cannot finish layout while this mutation
                    # holds the tree fence. Release that fence before compensation.
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
                        await reader.enter_async_context(self.preserve_reader(widget, position=position))
                        yield
                    finally:
                        self._history_mutation_root = previous
            finally:
                # Held layout requests become actionable only after the actual
                # outer native lock releases. Wake their original Screen before
                # the reader scope can wait for that compensated layout.
                if not self.lock.is_locked:
                    screen.check_idle()

    @asynccontextmanager
    async def preserve_reader(self, widget: Widget | None, *, position: WindowPosition | None = None):
        """Compensate reconstruction without owning its child source locks.

        A body worker owns its native mutation. A nested pager may acquire
        history_lock while constructing that body, so the reader lifetime
        cannot hold that lock or the window's native tree lock around it.
        Nested mutations borrow the acquired restoration even when it has no
        position; they cannot replace or release its outstanding compensation.
        """

        if self.history_restoration is not None:
            yield
            return
        screen = self.screen
        # A returning source already owns its intended point. Capturing the
        # temporary native viewport here creates a competing position which
        # can overwrite that reader after its first placement succeeds.
        position = self.pending_reader_position or position
        if position is None and widget is not None:
            position = HistoryAnchor.capture(widget, self)
        restoration = WindowRestoration(position)
        self.history_restoration = restoration
        geometry = self._geometry_revision
        try:
            try:
                yield
            finally:
                # The native source owns invalidation. An unchanged page or
                # already-live body must not manufacture another reflow.
                if self._geometry_revision != geometry:
                    restoration.request_layout(self)
            if self._geometry_revision == geometry:
                return
            # A reading position (a page row) or an anchor widget is applied
            # by the layout that places this change; without waiting for it,
            # the restoration ends first and the change moves the reader.
            anchored = restoration.position is not None or (
                widget is not None and widget.is_attached)
            if anchored and self.is_attached and screen.is_current:
                # A generic after-refresh callback can run before the pending
                # mount's layout. Wait for an actual compensated reflow first.
                await restoration.wait()
        finally:
            # Only the acquiring scope may release this exact operation.
            if self.history_restoration is restoration:
                self.history_restoration = None


@dataclass(frozen=True)
class HistoryAnchor(WindowPosition):
    widget: Widget
    scroll_y: float
    scroll_revision: int
    follow_tail: ClassVar[bool]

    @classmethod
    def capture(cls, widget: Widget, window: HistoryWindow) -> "HistoryAnchor":
        # Screen coordinates may still describe the frame before a scroll event.
        if window.follows_tail:
            return TailAnchor(widget, window.scroll_y, window.scroll_revision)
        return RecordAnchor(
            widget, window.scroll_y, window.scroll_revision, cls._offset(widget, window),
        )

    def before_layout(self, window: HistoryWindow) -> HistoryAnchor:
        """Rebind on navigation; layout clamps never replace reader intent."""
        if (window.follows_tail != self.follow_tail
                or window.scroll_revision != self.scroll_revision):
            return self.capture(self.widget, window)
        return self

    def required_bodies(self, window: HistoryWindow) -> tuple[Widget, ...]:
        """Preserve the transaction's existing target mount/size lifecycle.

        Tail policy skips offset lookup, not native target publication during
        incremental admission. Keep that separate from choosing compensation.
        """
        return (self.widget,) if self.widget.is_attached else ()

    @staticmethod
    def _placed_offset(widget: Widget, window: Widget) -> int | None:
        """The widget's row in the window's arranged layout, or None if unplaced.

        Viewport layout places what is on screen plus the screen's declared
        geometry targets, so None means the widget is off screen.
        """
        offset = 0
        node = widget
        geometry = widget.screen._compositor._layout_map
        while node is not window:
            if (placed := geometry.get(node)) is None:
                return None
            offset += placed.virtual_region.y
            if not isinstance(node.parent, Widget):
                break
            node = node.parent
        return offset

    @classmethod
    def _offset(cls, widget: Widget, window: Widget) -> int:
        """The row of a widget that layout must have placed: an anchor or target."""
        if (offset := cls._placed_offset(widget, window)) is None:
            raise LookupError(f"{widget!r} is not placed in {window!r}'s layout; "
                              "anchors must be visible or declared geometry targets")
        return offset

    def current(self, window: HistoryWindow) -> bool:
        return window.scroll_revision == self.scroll_revision

    @abstractmethod
    def _restore(self, window: HistoryWindow) -> bool:
        """Apply this policy to the newly committed layout."""


@dataclass(frozen=True)
class TailAnchor(HistoryAnchor):
    """Following the bottom has no dependency on a particular record's position."""

    follow_tail: ClassVar[bool] = True

    def _restore(self, window: HistoryWindow) -> bool:
        window.scroll_y = window.max_scroll_y
        return True


@dataclass(frozen=True)
class RecordAnchor(HistoryAnchor):
    """Keep a source record at the reader's chosen viewport offset."""

    virtual_y: int
    follow_tail: ClassVar[bool] = False

    def _restore(self, window: HistoryWindow) -> bool:
        if self.widget.is_attached:
            # This is document placement compensation, not a new user scroll.
            # scroll_to finishes the current animation even when the delta is
            # zero. The enclosing restoration translates its original curve.
            window.scroll_y = self.scroll_y + self._offset(self.widget, window) - self.virtual_y
            return True
        return False


@dataclass(frozen=True)
class LineAnchor(HistoryAnchor):
    """Keep the reader's row inside a fragment of a line-drawn transcript page.

    virtual_y is the fragment's first row in window coordinates at capture;
    rows changing above it, in this page or earlier ones, are compensated.
    """

    fragment: object = field(kw_only=True)
    virtual_y: int = field(kw_only=True)
    follow_tail: ClassVar[bool] = False

    def before_layout(self, window: HistoryWindow) -> HistoryAnchor:
        if window.follows_tail or window.scroll_revision != self.scroll_revision:
            from toad.widgets.transcript_history import TranscriptHistory

            return self.widget.query_ancestor(TranscriptHistory).reader_position(window)
        return self

    def _restore(self, window: HistoryWindow) -> bool:
        page = self.widget
        first = page.fragment_line(self.fragment) if page.is_attached else None
        if first is None:
            return False
        window.scroll_y = self.scroll_y + self._offset(page, window) + first - self.virtual_y
        return True
