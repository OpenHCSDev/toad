"""Stable scroll anchoring shared by both saved and IRC history paging."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from functools import cached_property
from contextlib import asynccontextmanager
import asyncio
from typing import TYPE_CHECKING, ClassVar
from weakref import WeakSet

from textual.widget import Widget
from textual.containers import VerticalScroll
from toad.widgets.viewport_body import DocumentViewport

if TYPE_CHECKING:
    from toad.widgets.tool_call import ToolCall
    from toad.widgets.transcript_history import TranscriptHistory


class ReaderPosition(ABC):
    """Source-owned reader intent, independent of retired widget geometry."""

    @classmethod
    def capture(cls, window: "HistoryWindow") -> "ReaderPosition":
        # Follow intent enters from Textual's native scroll boundary once.
        return TailReaderPosition() if window.follows_tail else OffsetReaderPosition(window.scroll_y)

    @abstractmethod
    def restore(self, window: "HistoryWindow") -> None: ...


@dataclass(frozen=True)
class TailReaderPosition(ReaderPosition):
    def restore(self, window: "HistoryWindow") -> None:
        window.anchor()


@dataclass(frozen=True)
class OffsetReaderPosition(ReaderPosition):
    y: float

    def restore(self, window: "HistoryWindow") -> None:
        window.release_anchor()
        window.scroll_to(y=self.y, animate=False, immediate=True)


class HistoryWindow(VerticalScroll):
    """Explicit follow intent survives zero-height scroll ranges during reflow."""

    CACHE_SUBTREE_GEOMETRY = True
    WARM_DOCUMENT_BODIES = DocumentViewport.DEFAULT_WARM_BODIES
    """Tunable number of recently visible document bodies retained offscreen."""

    scroll_revision = 0
    _restoring = False
    history_anchor: HistoryAnchor | None = None
    history_layout_ready: asyncio.Event | None = None
    history_paint_ready: asyncio.Event | None = None

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
        return DocumentViewport(self, max_warm_bodies=self.WARM_DOCUMENT_BODIES)

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
        if (self.max_scroll_y > 0 and not self.history_lock.locked()
                and self.history_anchor is None):
            super()._check_anchor()

    def check_follow(self) -> bool:
        self._check_anchor()
        if self.history_anchor is not None or not self.follows_tail:
            return False
        previous = self.scroll_y
        self._scroll_to(y=self.max_scroll_y, animate=False, release_anchor=False)
        return previous != self.scroll_y

    @asynccontextmanager
    async def preserve_history(self, widget: Widget | None):

        """Serialize with history_lock; reflow retains the current reader position."""
        from toad.screens.workspace import WorkspaceScreen

        screen = self.screen
        self.history_anchor = HistoryAnchor.capture(widget, self) if widget is not None else None
        if self.history_anchor is not None and isinstance(screen, WorkspaceScreen):
            screen.viewport_presentation.anchors.add(self)
        try:
            yield
            if (widget is not None and widget.is_attached and self.is_attached
                    and screen.is_current):
                # A generic after-refresh callback can run before the pending
                # mount's layout. Wait for an actual compensated reflow first.
                self.history_layout_ready = asyncio.Event()
                self.refresh(layout=True)
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
class HistoryAnchor(ABC):
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

    def restore(self, window: HistoryWindow) -> None:
        if window.scroll_revision != self.scroll_revision:
            return
        window._restoring = True
        try:
            self._restore(window)
        finally:
            window._restoring = False

    @abstractmethod
    def _restore(self, window: HistoryWindow) -> None:
        """Apply this policy to the newly committed layout."""


@dataclass(frozen=True)
class TailAnchor(HistoryAnchor):
    """Following the bottom has no dependency on a particular record's position."""

    follow_tail: ClassVar[bool] = True

    def _restore(self, window: HistoryWindow) -> None:
        window.anchor()


@dataclass(frozen=True)
class RecordAnchor(HistoryAnchor):
    """Keep a source record at the reader's chosen viewport offset."""

    virtual_y: int
    follow_tail: ClassVar[bool] = False

    def _restore(self, window: HistoryWindow) -> None:
        if self.widget.is_attached:
            window.release_anchor()
            window.scroll_to(
                y=self.scroll_y + self._offset(self.widget, window) - self.virtual_y,
                animate=False, immediate=True,
            )
