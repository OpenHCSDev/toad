"""Reusable Static-style Rich view whose heavy preparation always uses workers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import cast

from rich.console import RenderableType
from rich.cells import cell_len
from rich.protocol import is_renderable
from textual.geometry import Size
from textual.screen import Screen
from textual.selection import Selection
from textual.strip import Strip
from textual.style import Style
from textual.widget import Widget
from textual.widgets import Static
from textual.visual import VisualType

from toad.app import ToadApp
from toad.render_tasks import RichRenderTask
from toad.rich_preparation import (
    PreparedRichContent, RenderableSource, RichColorSystem, RichPresentation, RichSource, SyntaxSource,
)


@dataclass(frozen=True)
class _Preparation:
    generation: int
    task: RichRenderTask


class WorkerStatic(Static):
    """Accept ordinary data-only Rich renderables without a per-view adapter.

    CPU workers own measurement and all Rich rendering. The UI measures cached
    dimensions and requests only visible prepared rows. One in-flight request
    per widget coalesces source/style/size changes, and stale results are ignored.
    """

    def __init__(self, content: RenderableType | RichSource, *, id: str | None = None,
                 classes: str | None = None) -> None:
        self._source = content if isinstance(content, RichSource) else RenderableSource(content)
        self._generation = 0
        self._wanted: _Preparation | None = None
        self._ready_request: _Preparation | None = None
        self._prepared: PreparedRichContent | None = None
        self._preparing = False
        self._ready = asyncio.Event()
        self._closed = False
        self._layout_screen: Screen | None = None
        super().__init__("Preparing preview…", markup=False, id=id, classes=classes)

    @classmethod
    def code(cls, text: str, *, filename: str, lexer: str | None = None,
             line_numbers: bool = True, themed: bool = False,
             filename_only: bool = False, id: str | None = None) -> WorkerStatic:
        """Prepare lexer discovery and native Syntax rendering in the worker."""
        return cls(SyntaxSource(text, filename, lexer=lexer,
                                theme="auto" if themed else "monokai",
                                line_numbers=line_numbers, filename_only=filename_only), id=id)

    def on_mount(self) -> None:
        self._closed = False
        self._ready.clear()
        self._layout_screen = self.screen
        self._layout_screen.screen_layout_refresh_signal.subscribe(self, self._layout_changed)
        self.call_after_refresh(self._request_preparation)

    def _layout_changed(self, _screen: Screen) -> None:
        self._request_preparation()

    def notify_style_update(self) -> None:
        super().notify_style_update()
        if self.is_attached:
            self.call_later(self._request_preparation)

    def set_source(self, content: RenderableType | RichSource) -> None:
        self._source = content if isinstance(content, RichSource) else RenderableSource(content)
        self._generation += 1
        self._prepared = None
        self._ready.clear()
        super().update("Preparing preview…")
        self._request_preparation()

    def update(self, content: VisualType | RichSource = "", *, layout: bool = True) -> None:
        """The usual Static update entry point also uses CPU preparation.

        Actual prepared dimensions determine layout; no caller adapter is needed.
        Textual-only visuals with UI callbacks are not transferable Rich data.
        """
        if not isinstance(content, RichSource) and not is_renderable(content):
            raise TypeError("WorkerStatic requires data-only Rich content or RichSource")
        self.set_source(cast(RenderableType | RichSource, content))

    def _request_preparation(self) -> None:
        if self._closed or self._pruning or not self.is_attached:
            return
        app = self.app
        assert isinstance(app, ToadApp)
        auto_width = self.styles.is_auto_width
        parent = self.parent
        width = (parent.scrollable_content_region.width
                 if auto_width and isinstance(parent, Widget) else self.size.width)
        width = max(1, width or app.size.width)
        presentation = RichPresentation(
            app.console_options.update(width=width, height=None, highlight=False),
            self.visual_style.rich_style, self.link_style if self.auto_links else None,
            auto_width, self._get_justify_method(), cast(RichColorSystem | None, app.console.color_system),
            app.current_theme.dark,
        )
        request = _Preparation(self._generation, RichRenderTask(self._source, presentation))
        self._wanted = request
        if request == self._ready_request:
            self._ready.set()
            return
        self._ready.clear()
        if not self._preparing:
            self._preparing = True
            self.run_worker(self._prepare(), group="rich-preparation", exit_on_error=False)

    async def _prepare(self) -> None:
        app = self.app
        assert isinstance(app, ToadApp)
        try:
            while not self._closed and self.is_attached:
                request = self._wanted
                if request is None or request == self._ready_request:
                    return
                try:
                    prepared = await app.render_processes.submit(request.task)
                except Exception as error:
                    if request == self._wanted and not self._closed and self.is_attached:
                        self._prepared = None
                        self._ready_request = request
                        super().update(f"Unable to prepare preview: {error}")
                        self._ready.set()
                    continue
                if self._closed or self._pruning or not self.is_attached:
                    return
                if request != self._wanted:
                    continue
                self._prepared = prepared
                self._ready_request = request
                self.refresh(layout=True)
                self._ready.set()
        finally:
            self._preparing = False

    async def wait_ready(self) -> None:
        await self._ready.wait()

    def on_unmount(self) -> None:
        self._closed = True
        if self._layout_screen is not None:
            self._layout_screen.screen_layout_refresh_signal.unsubscribe(self)
            self._layout_screen = None
        self._generation += 1
        self._wanted = None
        self._ready_request = None
        self._prepared = None
        self._ready.set()

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        if self._prepared is None:
            return None
        if isinstance(self._source, SyntaxSource) and not self._source.line_numbers:
            # Tool Read output historically copied its original source text,
            # including tabs and final blank lines. Rich's terminal rendering
            # can drop that last blank row; it must not truncate clipboard text.
            return selection.extract(self._source.code), "\n"
        text = "\n".join(line.text for line in self._prepared.lines)
        return selection.extract(text), "\n"

    def get_content_width(self, container: Size, viewport: Size) -> int:
        return (self._prepared.width if self._prepared is not None
                else super().get_content_width(container, viewport))

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return (len(self._prepared.lines) if self._prepared is not None
                else super().get_content_height(container, viewport, width))

    def render_line(self, y: int) -> Strip:
        prepared = self._prepared
        if prepared is None:
            return super().render_line(y)
        width, height = self.size
        horizontal, vertical = self.styles.content_align
        extra = max(0, height - len(prepared.lines))
        y -= extra if vertical == "bottom" else extra // 2 if vertical == "middle" else 0
        if not 0 <= y < len(prepared.lines):
            return Strip.blank(width, self.visual_style.rich_style)
        strip = prepared.lines[y]
        selection = self.text_selection
        span = selection.get_span(y) if selection is not None else None
        if span is not None:
            start, end = span
            text = strip.text
            start = cell_len(text[:start])
            end = strip.cell_length if end == -1 else cell_len(text[:end])
            selection_style = Style.from_styles(self.screen.get_component_styles("screen--selection")).rich_style
            strip = Strip.join((strip.crop(0, start), strip.crop(start, end).apply_style(selection_style),
                                strip.crop(end, strip.cell_length)))
        strip = strip.apply_offsets(0, y)
        space = max(0, width - strip.cell_length)
        left = space if horizontal == "right" else space // 2 if horizontal == "center" else 0
        if left:
            strip = Strip.join((Strip.blank(left, self.visual_style.rich_style), strip))
        return strip
