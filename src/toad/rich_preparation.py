"""Data-only Rich preparation shared by worker-backed views."""

from __future__ import annotations

import copyreg
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from io import StringIO
from typing import TYPE_CHECKING, Literal, cast

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
from toad.line_blocks import LineBlock, LineRole, ToolOutputRole, MutedRole

if TYPE_CHECKING:
    from textual.app import App

RichColorSystem = Literal["auto", "standard", "256", "truecolor", "windows"]


@dataclass(frozen=True)
class RichTextBody(LineBlock):
    """Decoded terminal text retains its spans in the shared line renderer."""

    content: Text
    role: type[LineRole] = ToolOutputRole
    bar: type[LineRole] | None = MutedRole

    @property
    def selection_text(self) -> str:
        return self.content.plain


def _rebuild_style(values: tuple[object, ...]) -> Style:
    style = Style.__new__(Style)
    for slot, value in zip(Style.__slots__, values):
        setattr(style, slot, value)
    return style


def _reduce_style(style: Style) -> tuple[object, ...]:
    # Rich compares Styles by a cached Python hash, salted per process. It must
    # not cross a process boundary or reach a task's content address: the same
    # style data would otherwise pickle differently once something hashed it.
    return _rebuild_style, (tuple(None if slot == "_hash" else getattr(style, slot)
                                  for slot in Style.__slots__),)


# Every task and result crosses the process boundary through pickle; this
# module is imported on both sides before either pickles.
copyreg.pickle(Style, _reduce_style)


class PreparedPaintSource:
    """Native paint which may be borrowed after its original publication.

    A missing resource keeps live layout available but forbids retaining a
    provisional preview. Capture borrows the resource identity; its owner
    remains responsible for source, style, width and publication currentness.
    """

    @property
    def presentation_ready(self) -> bool:
        """The native frame can use preceding paint or a settled error."""
        raise NotImplementedError

    @property
    def prepared_content(self) -> PreparedRichContent | None:
        raise NotImplementedError


class RichSource(ABC):
    """Picklable data which materializes Rich or native content in the worker."""

    @abstractmethod
    def materialize(self, presentation: RichPresentation) -> RenderableType | Content:
        """Construct the renderable without a widget, app or core service."""

    style_names: tuple[str, ...] = ()
    """Symbolic native styles required by this source's worker rendering."""

    def prepare(self, presentation: RichPresentation) -> PreparedRichContent:
        return prepare_rich(self, presentation)

    def same_source(self, other: RichSource) -> bool:
        """Mutable/custom renderables must acquire their supplied value again."""
        return False

    def capture_selection(self, selection: Selection | None,
                          style: NativeStyle | None) -> RichSource:
        return self

    def selected_text(self, selection: Selection, prepared: PreparedRichContent) -> str:
        return selection.extract(prepared.selection_text)


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
        return PreparedNativeContent(width, tuple(lines), content.plain)


@dataclass(frozen=True)
class ContentSource(NativeContentSource):
    """Already acquired native content retains its symbolic component styles."""

    value: Content

    def same_source(self, other: RichSource) -> bool:
        # Content equality is text-only. Spans also own formatting, links and
        # action targets, so only its native full-content comparison suffices.
        return (type(other) is type(self) and self.value.is_same(other.value)
                and self.selection == other.selection
                and self.selection_style == other.selection_style)

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

    def materialize(self, presentation: RichPresentation) -> RenderableType:
        return self.value


@dataclass(frozen=True)
class SyntaxPalette:
    """How code is highlighted under the current theme.

    Code is drawn in the terminal's ANSI colours, so it follows the theme's
    palette: natively under ANSI themes, and through the scheme's terminal
    palette under true-colour themes (pywal's palette under `wal`).
    """

    ansi: bool
    dark: bool

    @classmethod
    def of(cls, app: App) -> SyntaxPalette:
        """The palette under any Textual app's current theme: ANSI as `:ansi` answers it."""
        return cls(app.native_ansi_color, app.current_theme.dark)

    @property
    def pygments_theme(self) -> str:
        return "ansi_dark" if self.dark else "ansi_light"


@dataclass(frozen=True)
class SyntaxSource(RichSource):
    code: str
    filename: str
    lexer: str | None = None
    line_numbers: bool = True
    filename_only: bool = False

    def materialize(self, presentation: RichPresentation) -> Syntax:
        lexer = self.lexer
        if lexer is None:
            try:
                lexer = (get_lexer_for_filename(self.filename) if self.filename_only
                         else Syntax.guess_lexer(self.filename, self.code))
            except ClassNotFound:
                lexer = "text"
        return Syntax(self.code, lexer, theme=presentation.syntax.pygments_theme,
                      line_numbers=self.line_numbers,
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
    def retained_bytes(self) -> int:
        return 64 + sum(64 + 16 * line.cell_length for line in self.lines)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def selection_text(self) -> str:
        """Rich previews select their prepared terminal rows."""
        return self.text

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
    """Native strips and copy text share the worker-acquired source coordinates."""

    original_text: str

    @property
    def retained_bytes(self) -> int:
        return super().retained_bytes + 4 * len(self.original_text)

    @property
    def selection_text(self) -> str:
        return self.original_text

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
    syntax: SyntaxPalette
    styles: tuple[tuple[str, NativeStyle], ...] = ()
    rules: tuple[tuple[str, object], ...] = ()
    native_style: NativeStyle = NativeStyle()


def prepare_rich(source: RichSource, presentation: RichPresentation) -> PreparedRichContent:
    """Measure/highlight/wrap/segment with native Rich entirely in a worker."""
    options = presentation.options
    console = Console(file=StringIO(), width=options.max_width, height=options.max_height,
                      force_terminal=options.is_terminal, legacy_windows=options.legacy_windows,
                      color_system=presentation.color_system, highlight=False)
    renderable = source.materialize(presentation)
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
    return PreparedRichContent(width, lines)
