"""Stable scroll anchoring shared by both saved and IRC history paging."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
import asyncio
from typing import TYPE_CHECKING, ClassVar
from weakref import WeakSet

from textual.widget import Widget
from textual import events
from textual.containers import VerticalScroll
from toad.widgets.viewport_body import DocumentViewport, ViewportBody
from toad.rich_preparation import PreparedPaintSource
from toad.widgets.presentation_window import protected_presentations

if TYPE_CHECKING:
    from toad.widgets.tool_call import ToolCall
    from toad.widgets.transcript_history import TranscriptPageAdmission
    from toad.transcript_source_preparation import TranscriptSourcePreparation


class WindowRestoration(ABC):
    """Apply an owned layout intent without recording another user scroll."""

    def current(self, window: "HistoryWindow") -> bool:
        return True

    def restore(self, window: "HistoryWindow") -> None:
        if not self.current(window):
            return
        with self.geometry(window):
            self._restore(window)

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
                    window.document_viewport.lookahead.relocated(compensation)
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
    def _restore(self, window: "HistoryWindow") -> None: ...


class ReaderPosition(WindowRestoration):
    """Source-owned reader intent, independent of retired widget geometry."""

    @staticmethod
    def _translate_motion(window: "HistoryWindow", destination: float, compensation: float) -> None:
        """Explicit native navigation owns its new destination, not the old curve."""

    @classmethod
    def capture(cls, window: "HistoryWindow") -> "ReaderPosition":
        from toad.widgets.transcript_history import TranscriptHistory

        # Follow intent enters from Textual's native scroll boundary once.
        if window.follows_tail:
            return TailReaderPosition()
        # Parked pagers revoke source work and leave window.histories while
        # their original admitted pages remain in the native tree. Capture
        # those page ranges before eviction, including the parked resource.
        return OffsetReaderPosition(window.scroll_y, tuple(
            admission for history in window.query(TranscriptHistory)
            if history.window is window
            for admission in history.capture_reader_admissions()
        ))

    def prepare_history(self, history: "TranscriptSourcePreparation") -> None:
        """Tail readers use ordinary newest-page admission."""


@dataclass(frozen=True)
class TailReaderPosition(ReaderPosition):
    def _restore(self, window: "HistoryWindow") -> None:
        window.anchor()


@dataclass(frozen=True)
class OffsetReaderPosition(ReaderPosition):
    y: float
    admissions: tuple["TranscriptPageAdmission", ...]

    def prepare_history(self, history: "TranscriptSourcePreparation") -> None:
        history.restore_reader_admissions(self.admissions)

    def _restore(self, window: "HistoryWindow") -> None:
        window.release_anchor()
        window.scroll_to(y=self.y, animate=False, immediate=True)


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
    history_anchor: HistoryAnchor | None = None
    history_layout_ready: asyncio.Event | None = None
    _history_mutation_root: Widget | None = None

    def action_scroll_end(self) -> None:
        self.jump_to_latest()

    def jump_to_latest(self) -> None:
        """Follow the source tail, including pages outside the mounted window."""
        self.anchor()
        self.document_viewport.destination()
        for history in tuple(self.histories):
            if history.has_newer:
                history.request_latest()

    def prepare_history_layout(self) -> HistoryAnchor | None:
        anchor = self.history_anchor
        if anchor is None:
            return None
        if anchor.widget.is_attached:
            self.history_anchor = anchor.before_layout(self)
            return self.history_anchor
        return None

    def history_geometry_targets(self) -> tuple[Widget, ...]:
        anchor = self.history_anchor
        return anchor.geometry_targets if anchor is not None else ()

    def restore_history_layout(self, position: HistoryAnchor) -> bool:
        previous = self.scroll_y
        position.restore(self)
        # A held layout can clamp scroll before publishing the new source
        # position. That clamp is not a new reader intent. Keep the acquired
        # source/reader relation until this transaction finishes.
        self.history_anchor = position
        return self.scroll_y != previous

    def finish_history_layout(self) -> None:
        if self.history_layout_ready is not None:
            self.history_layout_ready.set()

    def retire_presentation_wait(self) -> None:
        """Release a transaction whose scene no longer promises another frame."""
        if self.history_layout_ready is not None:
            self.history_layout_ready.set()

    def on_unmount(self) -> None:
        self.retire_presentation_wait()
        if "document_viewport" in self.__dict__:
            self.document_viewport.membership.retire()

    @cached_property
    def document_viewport(self):
        return DocumentViewport(self)

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
        # Rejoin at the bottom after actual downward movement, including
        # keyboard, wheel and scrollbar input. Compensation uses the existing
        # restoration transaction and cannot choose a different reader policy.
        if (new_value > old_value and not self._restoring
                and all(not history.has_newer for history in self.histories)
                and self.document_viewport.source_tail_visible):
            # A lazy pager's mounted edge is not the source tail. Explicit End
            # still chooses follow through jump_to_latest; ordinary travel only
            # rejoins it once the current source has no unpublished newer rows.
            super()._check_anchor()

    def _size_updated(self, size, virtual_size, container_size, layout=True) -> bool:
        # Native size commit owns scrollbar clamping. Compensate that movement
        # here, without treating unrelated Screen layouts as reader restoration.
        with WindowRestoration.geometry(self):
            changed = super()._size_updated(size, virtual_size, container_size, layout)
        if changed:
            self.document_viewport.request()
        return changed

    def check_follow(self) -> bool:
        if self.history_anchor is not None or not self.follows_tail:
            return False
        previous = self.scroll_y
        with WindowRestoration.geometry(self):
            self.scroll_y = self.max_scroll_y
        return previous != self.scroll_y

    def history_mutating(self) -> bool:
        """Native tree locking is the publication fence, not source status."""
        return self.history_mutation_root is not None

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
        visible = self.screen._compositor.visible_widgets
        viewport = self.content_region
        for item in items:
            if item in visible:
                region, clip = visible[item]
                if (region.overlaps(viewport) and region.overlaps(clip)
                        and clip.overlaps(viewport)):
                    yield item

    def reader_anchor(self, fallback: Widget) -> Widget:
        """Extent publication preserves the reader, not the changed paragraph."""
        if self.history_anchor is not None:
            return self.history_anchor.widget
        if self.follows_tail:
            return fallback
        visible = self.screen._compositor.visible_widgets
        # The reader's original message owns the position even while its
        # paragraphs are preparing. A ready leaf in the next message cannot
        # replace that source identity as the first message acquires height.
        body = min(self.visible_history_items(self.document_viewport.owners),
                   key=lambda node: visible[node][0].y, default=None)
        # Source identity precedes paint readiness. Skipping an unprepared
        # paragraph selects a later source point; wrapping earlier text then
        # moves the reader to preserve a paragraph they never chose.
        sources = (node for node in visible
                   if (isinstance(node, PreparedPaintSource)
                       or (isinstance(node, ViewportBody) and node.body_retained_paint_ready))
                   if body is None or node is body or body in node.ancestors
                   if next((parent for parent in node.ancestors
                            if isinstance(parent, HistoryWindow)), None) is self)
        painted = self.visible_history_items(sources)
        return min(painted, key=lambda node: visible[node][0].y,
                   default=fallback if body is None else body)

    def protect_history(
        self, items, *, older: bool, fallback: Widget,
    ) -> tuple[Widget, set[Widget]]:
        """Keep the reader's painted records and interaction owners during paging.

        Source leaves supply their mounted presentations, not another copy of
        the scene. Both native and wire pages borrow this one published geometry
        and the window's original selection/focus before admitting or trimming.
        """
        items = tuple(items)
        retained = tuple(self.visible_history_items(items))
        anchor = retained[0 if older else -1] if retained else fallback
        protected = protected_presentations(items, self.screen._interaction_widgets())
        protected.update(retained)
        protected.add(anchor)
        return anchor, protected

    @asynccontextmanager
    async def preserve_history(self, widget: Widget | None, *, root: Widget | None = None):
        """Fence a native source mutation inside its reader layout lifetime."""
        async with AsyncExitStack() as reader:
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
                    await reader.enter_async_context(self.preserve_reader(widget))
                    yield
                finally:
                    self._history_mutation_root = previous

    @asynccontextmanager
    async def preserve_reader(self, widget: Widget | None):
        """Compensate reconstruction without owning its child source locks.

        A body worker owns its native mutation. A nested pager may acquire
        history_lock while constructing that body, so the reader lifetime
        cannot hold that lock or the window's native tree lock around it.
        Nested mutations use this original anchor; they cannot replace or
        clear the reader's outstanding compensation.
        """
        from toad.screens.workspace import WorkspaceScreen

        if self.history_anchor is not None:
            yield
            return
        screen = self.screen
        self.history_anchor = HistoryAnchor.capture(widget, self) if widget is not None else None
        if self.history_anchor is not None and isinstance(screen, WorkspaceScreen):
            screen.viewport_presentation.anchors.add(self)
        geometry = self._geometry_revision
        try:
            try:
                yield
            finally:
                # The native source owns invalidation. An unchanged page or
                # already-live body must not manufacture another reflow.
                if self._geometry_revision != geometry:
                    self.refresh(layout=True)
            if self._geometry_revision == geometry:
                return
            if (widget is not None and widget.is_attached and self.is_attached
                    and screen.is_current and self.document_viewport.accepts_frame()):
                # A generic after-refresh callback can run before the pending
                # mount's layout. Wait for an actual compensated reflow first.
                self.history_layout_ready = asyncio.Event()
                await self.history_layout_ready.wait()
        finally:
            if isinstance(screen, WorkspaceScreen):
                screen.viewport_presentation.anchors.discard(self)
            self.history_anchor = None
            self.history_layout_ready = None


@dataclass(frozen=True)
class HistoryAnchor(WindowRestoration):
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

    @property
    def geometry_targets(self) -> tuple[Widget, ...]:
        """Preserve the transaction's existing target mount/size lifecycle.

        Tail policy skips offset lookup, not native target publication during
        incremental admission. Keep that separate from choosing compensation.
        """
        return (self.widget,) if self.widget.is_attached else ()

    @staticmethod
    def _offset(widget: Widget, window: Widget) -> int:
        offset = 0
        node = widget
        compositor = widget.screen._compositor
        # Use the committed layout, just like Compositor.layers. After a full
        # reflow Textual may still flag its former scroll map as invalidated;
        # asking virtual_region then needlessly computes the entire tree again
        # merely to recover the anchor's already-measured coordinates.
        geometry = (compositor._visible_map if compositor._visible_map is not None
                    else compositor._full_map)
        while node is not window:
            placed = geometry.get(node)
            offset += placed.virtual_region.y if placed is not None else node.virtual_region.y
            if not isinstance(node.parent, Widget):
                break
            node = node.parent
        return offset

    def current(self, window: HistoryWindow) -> bool:
        return window.scroll_revision == self.scroll_revision

    @abstractmethod
    def _restore(self, window: HistoryWindow) -> None:
        """Apply this policy to the newly committed layout."""


@dataclass(frozen=True)
class TailAnchor(HistoryAnchor):
    """Following the bottom has no dependency on a particular record's position."""

    follow_tail: ClassVar[bool] = True

    def _restore(self, window: HistoryWindow) -> None:
        window.scroll_y = window.max_scroll_y


@dataclass(frozen=True)
class RecordAnchor(HistoryAnchor):
    """Keep a source record at the reader's chosen viewport offset."""

    virtual_y: int
    follow_tail: ClassVar[bool] = False

    def _restore(self, window: HistoryWindow) -> None:
        if self.widget.is_attached:
            # This is document placement compensation, not a new user scroll.
            # scroll_to finishes the current animation even when the delta is
            # zero. The enclosing restoration translates its original curve.
            window.scroll_y = self.scroll_y + self._offset(self.widget, window) - self.virtual_y
