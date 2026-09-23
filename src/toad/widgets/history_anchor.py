"""Stable scroll anchoring shared by both saved and IRC history paging."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from contextlib import asynccontextmanager
import asyncio
from typing import TYPE_CHECKING
from weakref import WeakSet

from textual.widget import Widget
from textual.containers import VerticalScroll

if TYPE_CHECKING:
    from toad.widgets.tool_call import ToolCall
    from toad.widgets.transcript_history import TranscriptHistory


class HistoryWindow(VerticalScroll):
    """Explicit follow intent survives zero-height scroll ranges during reflow."""

    scroll_revision = 0
    _restoring = False
    history_anchor: HistoryAnchor | None = None
    history_layout_ready: asyncio.Event | None = None

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

    def suspend_follow(self) -> None:
        super().release_anchor()

    def _check_anchor(self) -> None:
        if (self.max_scroll_y > 0 and not self.history_lock.locked()
                and self.history_anchor is None):
            super()._check_anchor()

    def check_follow(self) -> None:
        self._check_anchor()

    @asynccontextmanager
    async def preserve_history(self, widget: Widget | None):
        """Keep a retained record stationary through the mutation's first layout.

        Callers serialize mutations with history_lock. SessionView captures the
        *current* scroll position before each reflow, so input received while
        children mount is incorporated rather than undone by a late callback.
        """
        from toad.screens.session_view import SessionView

        screen = self.screen
        self.history_anchor = HistoryAnchor.capture(widget, self) if widget is not None else None
        if self.history_anchor is not None and isinstance(screen, SessionView):
            screen.history_anchors.add(self)
        try:
            yield
            if widget is not None and widget.is_attached:
                # A generic after-refresh callback can run before the pending
                # mount's layout. Wait for an actual compensated reflow first.
                self.history_layout_ready = asyncio.Event()
                self.refresh(layout=True)
                await self.history_layout_ready.wait()
                painted = asyncio.Event()
                self.call_after_refresh(painted.set)
                await painted.wait()
        finally:
            if isinstance(screen, SessionView):
                screen.history_anchors.discard(self)
            self.history_anchor = None
            self.history_layout_ready = None


@dataclass(frozen=True)
class HistoryAnchor:
    widget: Widget
    virtual_y: int
    scroll_y: float
    follow_tail: bool
    scroll_revision: int

    @classmethod
    def capture(cls, widget: Widget, window: HistoryWindow) -> "HistoryAnchor":
        # Screen coordinates may still describe the frame before a scroll event.
        return cls(
            widget, cls._offset(widget, window), window.scroll_y,
            window.follows_tail,
            window.scroll_revision,
        )

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
            if self.follow_tail:
                window.anchor()
            elif self.widget.is_attached:
                window.release_anchor()
                window.scroll_to(
                    y=self.scroll_y + self._offset(self.widget, window) - self.virtual_y,
                    animate=False, immediate=True,
                )
        finally:
            window._restoring = False
