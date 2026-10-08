"""Data-only Rich preparation shared by worker-backed views."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from io import StringIO
from typing import Literal, cast

from rich.console import Console, ConsoleOptions, ConsoleRenderable, JustifyMethod, RenderableType
from rich.segment import Segment
from rich.style import Style
from rich.syntax import ClassNotFound, Syntax
from pygments.lexers import get_lexer_for_filename
from rich.text import Text
from textual.render import measure
from textual.strip import Strip
from textual.geometry import Offset, Region
from textual.widget import _Styled
from textual.content import Content
from textual.style import Style as NativeStyle
from textual.selection import Selection
from textual.visual import RenderOptions

RichColorSystem = Literal["auto", "standard", "256", "truecolor", "windows"]


class RichSource(ABC):
    """Picklable data which materializes Rich or native content in the worker."""

    @abstractmethod
    def materialize(self) -> RenderableType | Content:
        """Construct the renderable without a widget, app or core service."""

    style_names: tuple[str, ...] = ()
    """Symbolic native styles required by this source's worker rendering."""

    def prepare(self, presentation: RichPresentation) -> PreparedRichContent:
        return prepare_rich(self, presentation)

    def capture_selection(self, selection: Selection | None,
                          style: NativeStyle | None) -> RichSource:
        return self

    def selected_text(self, selection: Selection, prepared: PreparedRichContent) -> str:
        return selection.extract(prepared.text)


@dataclass(frozen=True, kw_only=True)
class NativeContentSource(RichSource):
    """Native content decoding and wrapping share one worker implementation."""

    selection: tuple[tuple[int, int] | None, tuple[int, int] | None] | None = None
    selection_style: NativeStyle | None = None

    def capture_selection(self, selection: Selection | None,
                          style: NativeStyle | None) -> NativeContentSource:
        coordinates = (None if selection is None else
                       tuple(None if offset is None else (offset.x, offset.y)
                             for offset in selection))
        return replace(self, selection=coordinates, selection_style=style)

    @abstractmethod
    def materialize(self) -> Content:
        """Decode the original source to native Content in the renderer."""

    def selected_text(self, selection: Selection, prepared: PreparedRichContent) -> str:
        return selection.extract(self.materialize().plain)

    def prepare(self, presentation: RichPresentation) -> PreparedRichContent:
        content = self.materialize()
        styles = dict(presentation.styles)
        def get_style(style):
            return styles[style] if isinstance(style, str) else style
        width = presentation.options.max_width
        if presentation.auto_width:
            width = max(1, min(width, content.get_optimal_width(dict(presentation.rules), width)))
        lines = content.render_strips(
            width, None, presentation.native_style,
            RenderOptions(get_style, dict(presentation.rules),
                          None if self.selection is None else Selection(
                              *(None if offset is None else Offset(*offset)
                                for offset in self.selection)),
                          self.selection_style),
        )
        if presentation.link_style is not None:
            lines = [line._apply_link_style(presentation.link_style) for line in lines]
        return PreparedNativeContent(width, tuple(lines))


@dataclass(frozen=True)
class ContentSource(NativeContentSource):
    """Already acquired native content retains its symbolic component styles."""

    value: Content

    @classmethod
    def capture(cls, value: Content, selection: Selection | None,
                selection_style: NativeStyle | None) -> ContentSource:
        return cls(value).capture_selection(selection, selection_style)

    @property
    def style_names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(span.style for span in self.value.spans
                                   if isinstance(span.style, str)))

    def materialize(self) -> Content:
        return self.value


@dataclass(frozen=True)
class AnsiContentSource(NativeContentSource):
    """ANSI source is decoded with its original Rich parser in the worker."""

    value: str

    def materialize(self) -> Content:
        return Content.from_rich_text(Text.from_ansi(self.value))


@dataclass(frozen=True)
class RenderableSource(RichSource):
    value: RenderableType

    def materialize(self) -> RenderableType:
        return self.value


@dataclass(frozen=True)
class SyntaxSource(RichSource):
    code: str
    filename: str
    lexer: str | None = None
    theme: str = "monokai"
    line_numbers: bool = True
    filename_only: bool = False

    def materialize(self) -> Syntax:
        lexer = self.lexer
        if lexer is None:
            try:
                lexer = (get_lexer_for_filename(self.filename) if self.filename_only
                         else Syntax.guess_lexer(self.filename, self.code))
            except ClassNotFound:
                lexer = "text"
        return Syntax(self.code, lexer, theme=self.theme, line_numbers=self.line_numbers,
                      word_wrap=False, background_color="default")

    def selected_text(self, selection: Selection, prepared: PreparedRichContent) -> str:
        # Read output owns its original tabs and final blank lines, which Rich
        # terminal rows may omit. Numbered previews retain row-based selection.
        return (selection.extract(self.code) if not self.line_numbers
                else super().selected_text(selection, prepared))


@dataclass(frozen=True)
class PreparedRichContent:
    width: int
    lines: tuple[Strip, ...]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def render_lines(self, crop: Region, *, selection=None, selection_style=None) -> list[Strip]:
        """Crop original prepared rows without rebuilding a native subtree."""
        result = []
        for y in crop.line_range:
            strip = self.lines[y] if 0 <= y < len(self.lines) else Strip.blank(self.width)
            span = selection.get_span(y) if selection is not None else None
            if span is not None:
                from rich.cells import cell_len
                first, last = span
                first = cell_len(strip.text[:first])
                last = strip.cell_length if last == -1 else cell_len(strip.text[:last])
                strip = Strip.join((strip.crop(0, first),
                                    strip.crop(first, last).apply_style(selection_style),
                                    strip.crop(last, strip.cell_length)))
            result.append(strip.apply_offsets(0, y).crop(crop.x, crop.right))
        return result


@dataclass(frozen=True)
class PreparedNativeContent(PreparedRichContent):
    """Native strips already carry original source selection offsets."""

    def render_lines(self, crop: Region, *, selection=None, selection_style=None) -> list[Strip]:
        lines = [self.lines[y] if 0 <= y < len(self.lines) else Strip.blank(self.width)
                 for y in crop.line_range]
        # Native Content may return a full row wider than its measurement
        # (for example a folded Unicode row). The widget's styles cache owns
        # final clipping; borrowing the full row must preserve its metadata.
        return lines if crop.x == 0 and crop.width == self.width else [
            line.crop(crop.x, crop.right) for line in lines]


@dataclass(frozen=True)
class RichPresentation:
    options: ConsoleOptions
    base_style: Style
    link_style: Style | None
    auto_width: bool
    justify: JustifyMethod | None
    color_system: RichColorSystem | None
    dark: bool = True
    styles: tuple[tuple[str, NativeStyle], ...] = ()
    rules: tuple[tuple[str, object], ...] = ()
    native_style: NativeStyle = NativeStyle()


def prepare_rich(source: RichSource, presentation: RichPresentation) -> PreparedRichContent:
    """Measure/highlight/wrap/segment with native Rich entirely in a worker."""
    options = presentation.options
    console = Console(file=StringIO(), width=options.max_width, height=options.max_height,
                      force_terminal=options.is_terminal, legacy_windows=options.legacy_windows,
                      color_system=presentation.color_system, highlight=False)
    if isinstance(source, SyntaxSource) and source.theme == "auto":
        source = replace(source, theme="ansi_dark" if presentation.dark else "ansi_light")
    renderable = source.materialize()
    if isinstance(renderable, Content):
        # Capture only the source's declared style inputs on the native side;
        # span merging, link metadata and full text conversion stay here.
        styles = dict(presentation.styles)
        text = Text(justify=presentation.justify)
        for part, style in renderable.render(end="", parse_style=styles.__getitem__):
            text.append(part, style.rich_style)
        renderable = text
    elif isinstance(renderable, str):
        renderable = Text.from_markup(renderable, justify=presentation.justify)
    elif isinstance(renderable, Text) and presentation.justify is not None:
        renderable = renderable.copy()
        renderable.justify = presentation.justify
    width = max(1, measure(console, renderable, options.max_width,
                           container_width=options.max_width) if presentation.auto_width else options.max_width)
    segments = console.render(
        _Styled(cast(ConsoleRenderable, renderable), presentation.base_style, presentation.link_style),
        options.update(width=width, height=None, highlight=False),
    )
    lines = tuple(Strip(line) for line in Segment.split_and_crop_lines(
        segments, width, include_new_lines=False, pad=False,
    ))
    # Rich compares Styles via its cached Python hash. That hash is salted per
    # process and must not travel with otherwise identical style data. Clear
    # only this derived cache, in the worker, before the result is serialized.
    seen: set[int] = set()
    for line in lines:
        for _, style, _ in line:
            if style is not None and id(style) not in seen:
                seen.add(id(style))
                style._hash = None
    return PreparedRichContent(width, lines)
