"""Sidebar rows scroll horizontally; their header controls stay in the viewport."""

from __future__ import annotations

from fractions import Fraction

from textual.box_model import BoxModel
from textual.containers import HorizontalGroup, VerticalScroll
from textual.geometry import Size


class SidebarHeader(HorizontalGroup):
    DEFAULT_CSS = "SidebarHeader { width: 100%; }"

    def _get_box_model(
        self, container: Size, viewport: Size,
        width_fraction: Fraction, height_fraction: Fraction,
        constrain_width: bool = False, greedy: bool = True,
    ) -> BoxModel:
        # The immediate auto-width group belongs to the wide body. Header
        # controls instead consume the enclosing scrollport's native width.
        width = self.query_ancestor(SidebarViewport).scrollable_content_region.width
        return super()._get_box_model(
            container.with_width(width), viewport, width_fraction, height_fraction,
            constrain_width, greedy,
        )

    def on_mount(self) -> None:
        self.query_ancestor(SidebarViewport).align_header(self)


class SidebarViewport(VerticalScroll):
    """Own scrollbar geometry and the horizontal position of sidebar headers."""

    CACHE_SUBTREE_GEOMETRY = True

    def preserve_reader(self, placements) -> None:
        placement = next((p for p in placements if self.scroll_y
                          and p.widget.region.y <= self.content_region.y < p.widget.region.bottom
                          and p.widget.is_navigation_row()), None)
        if placement is None:
            return
        delta = placement.region.y - placement.widget.virtual_region.y
        if not delta:
            return
        before = self.scroll_y
        self.scroll_y += delta
        shift = self.scroll_y - before
        self.app.animator.transform_running_animation(self, "scroll_y", lambda value: value + shift)
        self.scroll_target_y += shift

    def on_mount(self) -> None:
        self.watch(self, "scroll_x", self._align_headers, init=False)
        self._align_headers()

    def on_resize(self) -> None:
        # Native resize commits the scrollport, including its scrollbar gutter.
        # Invalidate only dependent headers; never store a second pixel width.
        for header in self.query(SidebarHeader):
            header.refresh(repaint=False, layout=True)

    def align_header(self, header: SidebarHeader) -> None:
        # The content still owns its full intrinsic width. Counter only its
        # horizontal scroll for these one-line headers, without pinning y or
        # creating a second read/presentation authority.
        header.styles.offset = (int(self.scroll_x), 0)

    def _align_headers(self) -> None:
        if self.is_mounted:
            for header in self.query(SidebarHeader):
                self.align_header(header)
