"""Sidebar rows scroll horizontally; their header controls stay in the viewport."""

from __future__ import annotations

from textual.containers import HorizontalGroup, VerticalScroll
from textual.geometry import Size
from textual.layout import DockArrangeResult


class SidebarHeader(HorizontalGroup):
    def on_mount(self) -> None:
        viewport = next((node for node in self.walk_ancestors()
                         if isinstance(node, SidebarViewport)), None)
        if viewport is not None:
            viewport.align_header(self)


class SidebarViewport(VerticalScroll):
    """Own scrollbar geometry and the horizontal position of sidebar headers."""

    CACHE_SUBTREE_GEOMETRY = True

    def on_mount(self) -> None:
        self.watch(self, "scroll_x", self._align_headers, init=False)
        self._align_headers()

    def arrange(self, size: Size, optimal: bool = False) -> DockArrangeResult:
        # Native layout supplies this pass's child viewport after its border
        # and scrollbar policy. Publish before arranging the headers, rather
        # than borrowing the previous committed size in a later Resize event.
        for header in self.query(SidebarHeader):
            header.set_styles(width=size.width)
        return super().arrange(size, optimal=optimal)

    def align_header(self, header: SidebarHeader) -> None:
        # The content still owns its full intrinsic width. Counter only its
        # horizontal scroll for these one-line headers, without pinning y or
        # creating a second read/presentation authority.
        header.set_styles(offset=(int(self.scroll_x), 0))

    def _align_headers(self) -> None:
        if self.is_mounted:
            for header in self.query(SidebarHeader):
                self.align_header(header)
