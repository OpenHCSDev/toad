"""Data-only Rich preparation shared by worker-backed views."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import StringIO
from typing import Literal, cast

from rich.console import Console, ConsoleOptions, ConsoleRenderable, JustifyMethod, RenderableType
from rich.segment import Segment
from rich.style import Style
from rich.syntax import ClassNotFound, Syntax
from rich.text import Text
from textual.render import measure
from textual.strip import Strip
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

    def materialize(self) -> Syntax:
        lexer = self.lexer
        if lexer is None:
            try:
                lexer = Syntax.guess_lexer(self.filename, self.code)
            except ClassNotFound:
                lexer = "text"
        return Syntax(self.code, lexer, theme=self.theme, line_numbers=self.line_numbers,
                      word_wrap=False, background_color="default")


@dataclass(frozen=True)
class PreparedRichContent:
    width: int
    lines: tuple[Strip, ...]


@dataclass(frozen=True)
class RichPresentation:
    options: ConsoleOptions
    base_style: Style
    link_style: Style | None
    auto_width: bool
    justify: JustifyMethod | None
    color_system: RichColorSystem | None


def prepare_rich(source: RichSource, presentation: RichPresentation) -> PreparedRichContent:
    """Measure/highlight/wrap/segment with native Rich entirely in a worker."""
    options = presentation.options
    console = Console(file=StringIO(), width=options.max_width, height=options.max_height,
                      force_terminal=options.is_terminal, legacy_windows=options.legacy_windows,
                      color_system=presentation.color_system, highlight=False)
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
