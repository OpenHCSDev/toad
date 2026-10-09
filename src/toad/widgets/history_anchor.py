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
from toad.widgets.viewport_body import DocumentViewport, ViewportBody
from toad.rich_preparation import PreparedPaintSource
from toad.widgets.presentation_window import protected_presentations

if TYPE_CHECKING:
    from textual.document._markdown import MarkdownSourceBlock
    from toad.widgets.tool_call import ToolCall
    from toad.transcript_preparation import TranscriptPageAdmission
    from toad.transcript_source_preparation import TranscriptSourcePreparation
    from toad.widgets.transcript_fragments import TranscriptFragment


class WindowRestoration(ABC):
    """Apply an owned layout intent without recording another user scroll."""

    def required_bodies(self, window: "HistoryWindow") -> tuple[Widget, ...]:
        """The original intent supplies its preparation and placement roots."""
        return ()

    def before_layout(self, window: "HistoryWindow") -> "WindowRestoration":
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
    def _restore(self, window: "HistoryWindow") -> bool: ...


class ReaderPosition(WindowRestoration):
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
        visible = window.screen._compositor.visible_widgets
        records = tuple(window.visible_history_items(
            fragment for history in histories for fragment in history.fragment_views
        ))
        viewport = window.content_region.intersection(window.screen.region)
        sources = (
            (record, source, region)
            for record in records
            for source, region in FragmentReaderPosition.source_regions(record)
            if region.overlaps(viewport)
        )
        first = min(sources, key=lambda item: max(item[2].y, viewport.y), default=None)
        if first is not None:
            record, source, region = first
            placement = FragmentReaderPosition.source_offset(record, window, region)
            if placement is not None:
                return DocumentReaderPosition(
                    record.fragment, window.scroll_y - placement, admissions, source=source,
                )
        record = min(records, key=lambda fragment: visible[fragment][0].y, default=None)
        if record is not None:
            return FragmentReaderPosition(
                record.fragment, window.scroll_y - HistoryAnchor._offset(record, window),
                admissions,
            )
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
        return next((record for history in window.transcript_histories()
                     for record in history.fragment_views
                     if record.fragment is self.fragment), None)

    def current(self, window: "HistoryWindow") -> bool:
        record = self.record(window)
        return record is not None and record.display

    def required_bodies(self, window: "HistoryWindow") -> tuple[Widget, ...]:
        record = self.record(window)
        return () if record is None else (record,)

    def placement(self, window: "HistoryWindow") -> int | None:
        record = self.record(window)
        if record is None or not record.body_ready:
            return None
        return HistoryAnchor._offset(record, window, require_placement=True)

    @staticmethod
    def source_bodies(record):
        """Borrow original body boundaries and each source cursor's geometry.

        Containers own child resources; no reader walks prepared native blocks
        or builds an alternate source/placement catalog.
        """
        from toad.block_content import BlockContent

        pending = [record]
        while pending:
            body = pending.pop()
            if isinstance(body, BlockContent):
                yield body
            pending.extend(reversed(tuple(body.child_bodies())))

    @classmethod
    def source_regions(cls, record):
        for body in cls.source_bodies(record):
            yield from body.block_cursor.source_regions()

    @staticmethod
    def source_offset(record, window, region) -> int | None:
        geometry = window.screen._compositor._published_map.get(record)
        if geometry is None:
            return None
        placed = HistoryAnchor._offset(record, window, require_placement=True)
        return None if placed is None else placed + region.y - geometry.region.y

    def _restore(self, window: "HistoryWindow") -> bool:
        placed = self.placement(window)
        return self._restore_row(window, None if placed is None else placed + self.offset)


@dataclass(frozen=True)
class DocumentReaderPosition(FragmentReaderPosition):
    """The actual Markdown member owns the reading row, not its headers.

    Row offset is relative to that source block's committed placement. This
    preserves the reader across scene eviction and changing preceding rows;
    it does not claim a character position through a width-dependent rewrap.
    """

    source: MarkdownSourceBlock = field(kw_only=True)

    def required_bodies(self, window: "HistoryWindow") -> tuple[Widget, ...]:
        record = self.record(window)
        if record is None:
            return ()
        return (record, *(body for body in self.source_bodies(record)
                          if body.block_cursor.owns_source(self.source)))

    def current(self, window: "HistoryWindow") -> bool:
        if not super().current(window):
            return False
        return (any(
                    acquired.document is not None
                    and self.source.document.same_source(acquired.document)
                    for acquired in self.fragment.resolved_sources()
                ) or any(
                    body.block_cursor.owns_source(self.source)
                    for body in self.source_bodies(self.record(window))
                ))

    def placement(self, window: "HistoryWindow") -> int | None:
        record = self.record(window)
        if record is None:
            return None
        for source, region in self.source_regions(record):
            if (source.source_index == self.source.source_index
                    and source.document.same_source(self.source.document)):
                return self.source_offset(record, window, region)
        return None


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
    history_anchor: WindowRestoration | None = None
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

    def prepare_history_layout(self) -> WindowRestoration | None:
        anchor = self.history_anchor
        if anchor is None:
            return None
        if all(body.is_attached for body in anchor.required_bodies(self)):
            self.history_anchor = anchor.before_layout(self)
            return self.history_anchor
        return None

    @property
    def pending_reader_position(self) -> ReaderPosition | None:
        """A source-owning window lends its actual pending restoration."""
        return None

    @property
    def reader_bodies(self) -> tuple[Widget, ...]:
        position = self.pending_reader_position
        return () if position is None else position.required_bodies(self)

    def history_geometry_targets(self) -> tuple[Widget, ...]:
        anchor = self.history_anchor
        return tuple(dict.fromkeys((*self.reader_bodies,
                                    *(anchor.required_bodies(self) if anchor is not None else ()))))

    def restore_history_layout(self, position: WindowRestoration) -> bool:
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

    def on_mount(self) -> None:
        self.document_viewport.request_after_refresh()

    def on_viewport_layout(self, _screen) -> None:
        self.document_viewport.request_after_refresh()

    def prepare_viewport(self) -> None:
        """Native publication, rather than raw motion, owns visible tools."""
        self.hydrate_visible_tools()

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
            elif not isinstance(node, ViewportBody):
                pending.extend(reversed(node.children))

    def reader_anchor(self, fallback: Widget) -> Widget:
        """Extent publication preserves the reader, not the changed paragraph."""
        if self.history_anchor is not None:
            roots = self.history_anchor.required_bodies(self)
            if roots:
                return roots[0]
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
                        await reader.enter_async_context(self.preserve_reader(widget))
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
        # A returning source already owns its intended point. Capturing the
        # temporary native viewport here creates a competing position which
        # can overwrite that reader after its first placement succeeds.
        self.history_anchor = self.pending_reader_position
        if self.history_anchor is None and widget is not None:
            self.history_anchor = HistoryAnchor.capture(widget, self)
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

    def required_bodies(self, window: HistoryWindow) -> tuple[Widget, ...]:
        """Preserve the transaction's existing target mount/size lifecycle.

        Tail policy skips offset lookup, not native target publication during
        incremental admission. Keep that separate from choosing compensation.
        """
        return (self.widget,) if self.widget.is_attached else ()

    @staticmethod
    def _offset(widget: Widget, window: Widget, *, require_placement: bool = False) -> int | None:
        offset = 0
        node = widget
        compositor = widget.screen._compositor
        # Use the committed layout, just like Compositor.layers. After a full
        # reflow Textual may still flag its former scroll map as invalidated;
        # asking virtual_region then needlessly computes the entire tree again
        # merely to recover the anchor's already-measured coordinates.
        geometry = compositor._published_map
        while node is not window:
            placed = geometry.get(node)
            if placed is None and require_placement:
                return None
            offset += placed.virtual_region.y if placed is not None else node.virtual_region.y
            if not isinstance(node.parent, Widget):
                break
            node = node.parent
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
