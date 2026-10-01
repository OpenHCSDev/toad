"""Stable scroll anchoring shared by both saved and IRC history paging."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from functools import cached_property
from contextlib import asynccontextmanager, contextmanager
import asyncio
from typing import TYPE_CHECKING, ClassVar
from weakref import WeakSet

from textual.widget import Widget
from textual.containers import VerticalScroll
from toad.widgets.viewport_body import DocumentViewport

if TYPE_CHECKING:
    from toad.widgets.tool_call import ToolCall
    from toad.widgets.transcript_history import TranscriptHistory, TranscriptPageAdmission


class WindowRestoration(ABC):
    """Apply an owned layout intent without recording another user scroll."""

    def current(self, window: "HistoryWindow") -> bool:
        return True

    def restore(self, window: "HistoryWindow") -> None:
        if not self.current(window):
            return
        with self.geometry(window):
            self._restore(window)

    @staticmethod
    @contextmanager
    def geometry(window: "HistoryWindow"):
        """Own native reflow and its compensation as one reader restoration."""
        restoring = window._restoring
        previous = window.scroll_y
        destination = window.scroll_target_y
        window._restoring = True
        try:
            yield
        finally:
            if not restoring:
                compensation = window.scroll_y - previous
                if compensation:
                    window.app.animator.transform_running_animation(
                        window, "scroll_y", lambda value: value + compensation,
                    )
                    window.scroll_target_y = destination + compensation
                window.document_viewport.lookahead.relocated(compensation)
            window._restoring = restoring

    @abstractmethod
    def _restore(self, window: "HistoryWindow") -> None: ...


class ReaderPosition(WindowRestoration):
    """Source-owned reader intent, independent of retired widget geometry."""

    @classmethod
    def capture(cls, window: "HistoryWindow") -> "ReaderPosition":
        # Follow intent enters from Textual's native scroll boundary once.
        if window.follows_tail:
            return TailReaderPosition()
        return OffsetReaderPosition(window.scroll_y, tuple(
            page.capture_admission()
            for history in window.histories for page in history.pages
        ))

    def prepare_history(self, history: "TranscriptHistory") -> None:
        """Tail readers use ordinary newest-page admission."""


@dataclass(frozen=True)
class TailReaderPosition(ReaderPosition):
    def _restore(self, window: "HistoryWindow") -> None:
        window.anchor()


@dataclass(frozen=True)
class OffsetReaderPosition(ReaderPosition):
    y: float
    admissions: tuple["TranscriptPageAdmission", ...]

    def prepare_history(self, history: "TranscriptHistory") -> None:
        for page in history.pages:
            for admission in self.admissions:
                page.restore_admission(admission)

    def _restore(self, window: "HistoryWindow") -> None:
        window.release_anchor()
        window.scroll_to(y=self.y, animate=False, immediate=True)


class HistoryWindow(VerticalScroll):
    """Reader movement owns follow intent; layout only applies it."""

    CACHE_SUBTREE_GEOMETRY = True
    scroll_revision = 0
    _restoring = False
    history_anchor: HistoryAnchor | None = None
    history_layout_ready: asyncio.Event | None = None
    history_paint_ready: asyncio.Event | None = None

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
        self.history_anchor = HistoryAnchor.capture(position.widget, self)
        return self.scroll_y != previous

    def finish_history_layout(self) -> None:
        if self.history_layout_ready is not None:
            self.history_layout_ready.set()

    def retire_presentation_wait(self) -> None:
        """Release a transaction whose scene no longer promises another frame."""
        for ready in (self.history_layout_ready, self.history_paint_ready):
            if ready is not None:
                ready.set()

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
    def histories(self) -> WeakSet[TranscriptHistory]:
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
        return self.lock.is_locked

    @asynccontextmanager
    async def preserve_history(self, widget: Widget | None):

        """Publish one native tree mutation, then its compensated reader layout."""
        from toad.screens.workspace import WorkspaceScreen

        screen = self.screen
        self.history_anchor = HistoryAnchor.capture(widget, self) if widget is not None else None
        if self.history_anchor is not None and isinstance(screen, WorkspaceScreen):
            screen.viewport_presentation.anchors.add(self)
        try:
            # Mount/remove await native child composition. Until the mutation
            # finishes, neither its page admission nor its extent is a scene
            # the reader can consume. Source preparation precedes this phase;
            # only this window's native tree lock holds its publication. A
            # departing tab must not suppress another window's frames.
            try:
                async with self.lock:
                    yield
            finally:
                self.refresh(layout=True)
            if (widget is not None and widget.is_attached and self.is_attached
                    and screen.is_current):
                # A generic after-refresh callback can run before the pending
                # mount's layout. Wait for an actual compensated reflow first.
                self.history_layout_ready = asyncio.Event()
                await self.history_layout_ready.wait()
                if not self.is_attached or not screen.is_current or not widget.is_attached:
                    return
                painted = self.history_paint_ready = asyncio.Event()
                self.call_after_refresh(painted.set)
                await painted.wait()
        finally:
            if isinstance(screen, WorkspaceScreen):
                screen.viewport_presentation.anchors.discard(self)
            self.history_anchor = None
            self.history_layout_ready = self.history_paint_ready = None


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
        """Refresh reader intent before layout, rebinding geometry only on transition."""
        if window.follows_tail != self.follow_tail:
            return self.capture(self.widget, window)
        return replace(self, scroll_y=window.scroll_y, scroll_revision=window.scroll_revision)

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
