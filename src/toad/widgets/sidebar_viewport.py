"""Sidebar rows scroll horizontally; their header controls stay in the viewport."""

from __future__ import annotations

from textual.containers import HorizontalGroup, VerticalScroll
from textual.geometry import Offset


class SidebarHeader(HorizontalGroup):
    DEFAULT_CSS = "SidebarHeader { width: 100%; }"

    def on_mount(self) -> None:
        viewport = next((node for node in self.walk_ancestors()
                         if isinstance(node, SidebarViewport)), None)
        if viewport is not None:
            viewport.align_header(self)


class SidebarViewport(VerticalScroll):
    """Own scrollbar geometry and the horizontal position of sidebar headers."""

    CACHE_SUBTREE_GEOMETRY = True

    def preserve_reader(self, placements) -> Offset:
        placement = next((p for p in placements if self.scroll_y
                          and p.widget.region.y <= self.content_region.y < p.widget.region.bottom
                          and p.widget.is_navigation_row()), None)
        if placement is None or not placement.widget.pending_move(placement):
            return Offset()
        before = self.scroll_y
        self.scroll_y += placement.region.y - placement.widget.virtual_region.y
        shift = self.scroll_y - before
        self.app.animator.transform_running_animation(self, "scroll_y", lambda value: value + shift)
        self.scroll_target_y += shift
        return Offset(0, round(shift))

    def on_mount(self) -> None:
        self.watch(self, "scroll_x", self._align_headers, init=False)
        self._align_headers()

    def align_header(self, header: SidebarHeader) -> None:
        # The content still owns its full intrinsic width. Counter only its
        # horizontal scroll for these one-line headers, without pinning y or
        # creating a second read/presentation authority.
        header.styles.offset = (int(self.scroll_x), 0)

    def _align_headers(self) -> None:
        if self.is_mounted:
            for header in self.query(SidebarHeader):
                self.align_header(header)
