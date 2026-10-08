"""Reusable Static-style Rich view whose heavy preparation always uses workers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import cast

from rich.console import RenderableType
from rich.protocol import is_renderable
from textual import events
from textual.message import Message
from textual._measurement import NATIVE_WIDGET_HEIGHT, NATIVE_WIDGET_WIDTH, height_dependency
from textual.content import Content
from textual.geometry import Region, Size
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
    ContentSource, PreparedPaintSource, PreparedRichContent, RenderableSource, RichPresentation, RichSource, SyntaxSource,
)


@dataclass(frozen=True)
class _Preparation:
    generation: int
    task: RichRenderTask


class WorkerStatic(PreparedPaintSource, Static):
    """Accept ordinary data-only Rich renderables without a per-view adapter.

    CPU workers own measurement and all Rich rendering. The UI measures cached
    dimensions and requests only visible prepared rows. One in-flight request
    per widget coalesces source/style/size changes, and stale results are ignored.
    """

    class ExtentReady(Message):
        """This source request's final extent has committed to native layout."""

    def __init__(self, content: RenderableType | RichSource | Content = "", *,
                 name: str | None = None, id: str | None = None,
                 classes: str | None = None, expand: bool = False,
                 shrink: bool = False, markup: bool = False, disabled: bool = False) -> None:
        self._source = self.source_for(content)
        self._generation = 0
        self._wanted: _Preparation | None = None
        self._ready_request: _Preparation | None = None
        self._prepared: PreparedRichContent | None = None
        self._preparing = False
        self._ready = asyncio.Event()
        self._closed = False
        self._layout_screen: Screen | None = None
        super().__init__("Preparing preview…", markup=False, name=name, id=id,
                         classes=classes, expand=expand, shrink=shrink, disabled=disabled)

    @staticmethod
    def source_for(content):
        if isinstance(content, RichSource):
            return content
        return ContentSource(content) if isinstance(content, Content) else RenderableSource(content)

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
        self.call_after_refresh(self._request_preparation, capture=True)

    def _layout_changed(self, _screen: Screen) -> None:
        if self.styles.is_auto_width:
            self._request_preparation()

    def on_resize(self, _event: events.Resize) -> None:
        self._request_preparation()

    def notify_style_update(self) -> None:
        super().notify_style_update()
        if self.is_attached:
            self.call_later(self._request_preparation, capture=True)

    def set_source(self, content: RenderableType | RichSource) -> None:
        source = self.source_for(content)
        if self._source.same_source(source):
            # Source equality does not exempt independently changing native
            # style, width or selection. Acquire their original request as usual.
            self._request_preparation(capture=True)
            return
        self._source = source
        self._generation += 1
        self._wanted = None
        self._ready.clear()
        # The ready request owns the preceding paint and copy coordinates.
        # Keep it until current replacement paint commits; it supplies no new
        # source readiness or read acknowledgement while that work is pending.
        if self._prepared is None:
            super().update("Preparing preview…")
        self._request_preparation(capture=True)

    def update(self, content: VisualType | RichSource = "", *, layout: bool = True) -> None:
        """The usual Static update entry point also uses CPU preparation.

        Actual prepared dimensions determine layout; no caller adapter is needed.
        Textual-only visuals with UI callbacks are not transferable Rich data.
        """
        if not isinstance(content, (RichSource, Content)) and not is_renderable(content):
            raise TypeError("WorkerStatic requires data-only Rich content or RichSource")
        self.set_source(cast(RenderableType | RichSource, content))

    def _request_preparation(self, *, capture: bool = False) -> None:
        if self._closed or self._pruning or not self.is_attached:
            return
        app = self.app
        assert isinstance(app, ToadApp)
        auto_width = self.styles.is_auto_width
        parent = self.parent
        width = (parent.scrollable_content_region.width
                 if auto_width and isinstance(parent, Widget)
                 else max(0, self.outer_size.width - self.styles.gutter.width))
        # A mounted node may not have its native box yet. App width is not
        # this widget's wrapping width; native Resize supplies the real
        # answer. Preparing the guessed width would discard a whole CPU job.
        if width <= 0:
            return
        options = app.console_options.update(width=width, height=None, highlight=False)
        link_style = self.link_style if self.auto_links and not self.screen._selecting else None
        wanted = self._wanted
        if not capture and wanted is not None and wanted.generation == self._generation:
            # Layout borrows the original acquired source/style/selection. Only
            # geometry and the screen's live link-selection admission change
            # here. Their own callbacks capture independently changed answers.
            presentation = wanted.task.presentation
            if (presentation.options == options and presentation.auto_width == auto_width
                    and presentation.link_style == link_style):
                request = wanted
            else:
                presentation = replace(presentation, options=options, auto_width=auto_width,
                                       link_style=link_style)
                request = replace(wanted, task=replace(wanted.task, presentation=presentation))
        else:
            selection = self.text_selection
            source = self._source.capture_selection(selection,
                Style.from_styles(self.screen.get_component_styles("screen--selection"))
                if selection is not None else None)
            native_style = self.visual_style
            presentation = RichPresentation(
                options, native_style.rich_style, link_style,
                auto_width, self._get_justify_method(), app.console.color_system,
                app.current_theme.dark,
                tuple((name, self._get_style(name)) for name in source.style_names),
                tuple((name, self.styles.get_rule(name))
                      for name in ("text_align", "text_overflow", "text_wrap", "line_pad")
                      if self.styles.has_rule(name)), native_style,
            )
            request = _Preparation(self._generation, RichRenderTask(source, presentation))
        self._wanted = request
        if request == self._ready_request:
            if not self._ready.is_set():
                self.call_after_refresh(self._publish_ready, request)
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
                        self.call_after_refresh(self._publish_ready, request)
                    continue
                if self._closed or self._pruning or not self.is_attached:
                    return
                if request != self._wanted:
                    continue
                previous = self._prepared
                layout = (previous is None or previous.width != prepared.width
                          or len(previous.lines) != len(prepared.lines))
                async with self.preparation_publication(layout=layout):
                    # Publication may await its original viewport's mutation
                    # custody. Source/style/width can change during that wait.
                    if self._closed or self._pruning or not self.is_attached or request != self._wanted:
                        continue
                    self._prepared = prepared
                    self._ready_request = request
                    self.refresh(layout=layout)
                    self.call_after_refresh(self._publish_ready, request)
        finally:
            self._preparing = False

    def _publish_ready(self, request: _Preparation) -> None:
        # Preparing rows and committing their native extent are separate
        # lifetimes. Retirement may borrow paint only after this sender's
        # original layout/refresh completes, for the same source request.
        if (not self._closed and self.is_attached
                and request == self._ready_request == self._wanted):
            completed = self._ready.is_set()
            self._ready.set()
            if not completed:
                self.post_message(self.ExtentReady())

    @property
    def preparation_complete(self) -> bool:
        """Successful rows and displayed errors both own a settled extent."""
        return (self._ready.is_set() and self._ready_request is not None
                and self._ready_request.generation == self._generation
                and self._ready_request == self._wanted)

    async def wait_ready(self) -> None:
        await self._ready.wait()

    @asynccontextmanager
    async def preparation_publication(self, *, layout: bool):
        """Views borrow their existing native reader lifetime for new extent."""
        yield

    @property
    def presentation_ready(self) -> bool:
        # Existing render_line and measurement retain preceding rows while a
        # replacement request prepares. A settled error also needs its first
        # frame before the after-refresh extent callback can complete.
        return (self._prepared is not None
                or (self._ready_request is not None and self._ready_request == self._wanted))

    @property
    def paint_ready(self) -> bool:
        """A placeholder or failed preview is not rendered source evidence."""
        return (self._prepared is not None and self._ready_request is not None
                and self._ready_request.generation == self._generation
                and self._ready_request == self._wanted)

    @property
    def prepared_content(self) -> PreparedRichContent | None:
        """Borrow the original current paint resource, never a loading preview."""
        return self._prepared if self.paint_ready and self._ready.is_set() else None

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
        if self._prepared is None or self._ready_request is None:
            return None
        return self._ready_request.task.source.selected_text(selection, self._prepared), "\n"

    @height_dependency(NATIVE_WIDGET_WIDTH)
    def get_content_width(self, container: Size, viewport: Size) -> int:
        return (self._prepared.width if self._prepared is not None
                else super().get_content_width(container, viewport))

    @height_dependency(NATIVE_WIDGET_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        # Tentative layout widths are measurements, not assigned geometry.
        # Native Resize and auto-width layout own the preparation demand.
        return (len(self._prepared.lines) if self._prepared is not None
                else super().get_content_height(container, viewport, width))

    def selection_updated(self, selection: Selection | None) -> None:
        super().selection_updated(selection)
        self._request_preparation(capture=True)

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
        selection = self.text_selection
        selection_style = (Style.from_styles(self.screen.get_component_styles("screen--selection")).rich_style
                           if selection is not None else None)
        strip = prepared.render_lines(Region(0, y, prepared.width, 1), selection=selection,
                                      selection_style=selection_style)[0]
        space = max(0, width - strip.cell_length)
        left = space if horizontal == "right" else space // 2 if horizontal == "center" else 0
        if left:
            strip = Strip.join((Strip.blank(left, self.visual_style.rich_style), strip))
        return strip
