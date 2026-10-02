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
from textual.geometry import Region
from textual.widget import _Styled

RichColorSystem = Literal["auto", "standard", "256", "truecolor", "windows"]


class RichSource(ABC):
    """Picklable data which materializes a Rich renderable in the CPU worker."""

    @abstractmethod
    def materialize(self) -> RenderableType:
        """Construct the renderable without a widget, app or core service."""


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
class RichPresentation:
    options: ConsoleOptions
    base_style: Style
    link_style: Style | None
    auto_width: bool
    justify: JustifyMethod | None
    color_system: RichColorSystem | None
    dark: bool = True


def prepare_rich(source: RichSource, presentation: RichPresentation) -> PreparedRichContent:
    """Measure/highlight/wrap/segment with native Rich entirely in a worker."""
    options = presentation.options
    console = Console(file=StringIO(), width=options.max_width, height=options.max_height,
                      force_terminal=options.is_terminal, legacy_windows=options.legacy_windows,
                      color_system=presentation.color_system, highlight=False)
    if isinstance(source, SyntaxSource) and source.theme == "auto":
        source = replace(source, theme="ansi_dark" if presentation.dark else "ansi_light")
    renderable = source.materialize()
    if isinstance(renderable, str):
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
