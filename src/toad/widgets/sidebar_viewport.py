"""Sidebar rows scroll horizontally; their header controls stay in the viewport."""

from __future__ import annotations

from textual.containers import HorizontalGroup, VerticalScroll


class SidebarHeader(HorizontalGroup):
    def on_mount(self) -> None:
        viewport = next((node for node in self.ancestors if isinstance(node, SidebarViewport)), None)
        if viewport is not None:
            viewport.align_header(self)


class SidebarViewport(VerticalScroll):
    """Own scrollbar geometry and the horizontal position of sidebar headers."""

    def on_mount(self) -> None:
        self.watch(self, "scroll_x", self._align_headers, init=False)
        self._align_headers()

    def on_resize(self) -> None:
        self._align_headers()

    def align_header(self, header: SidebarHeader) -> None:
        width = self.content_size.width - self.scrollbar_gutter.width
        if width <= 0:
            return
        # The content still owns its full intrinsic width. Counter only its
        # horizontal scroll for these one-line headers, without pinning y or
        # creating a second read/presentation authority.
        header.styles.width = width
        header.offset = (int(self.scroll_x), 0)

    def _align_headers(self) -> None:
        if self.is_mounted:
            for header in self.query(SidebarHeader):
                self.align_header(header)
