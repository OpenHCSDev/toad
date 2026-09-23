from collections.abc import Callable
from functools import lru_cache
from time import monotonic

from rich.segment import Segment
from rich.style import Style as RichStyle

from textual.visual import Visual
from textual.app import ScreenStackError, UnknownModeError
from textual.color import Color

from textual.style import Style
from textual.strip import Strip
from textual.visual import RenderOptions
from textual.widget import Widget
from textual.reactive import reactive
from textual.css.styles import RulesMap


COLORS = [
    "ansi_magenta",
    "ansi_red",
    "ansi_yellow",
    "ansi_green",
    "ansi_cyan",
    "ansi_blue",
]


class ThrobberVisual(Visual):
    """A Textual 'Visual' object.

    Analogous to a Rich renderable, but with support for transparency.

    """

    def __init__(
        self, character: str = "━", get_time: Callable[[], float] = monotonic
    ) -> None:
        self.character = character
        self.get_time = get_time

    colors = tuple(Color.parse(color).rich_color for color in COLORS)

    @lru_cache(maxsize=8)
    def make_segments(self, style: Style, width: int) -> list[Segment]:
        background = style.rich_style.bgcolor
        character = self.character
        color_count = len(self.colors)
        segments = [
            Segment(
                character,
                RichStyle.from_color(
                    self.colors[(offset * color_count // max(width, 1)) % color_count],
                    background,
                ),
            )
            for offset in range(width * 2)
        ]

        return segments

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions
    ) -> list[Strip]:
        """Render the Visual into an iterable of strips.

        Args:
            width: Width of desired render.
            height: Height of desired render or `None` for any height.
            style: The base style to render on top of.
            options: Additional render options.

        Returns:
            An list of Strips.
        """

        time = self.get_time()
        segments = self.make_segments(style, width)
        offset = width - int((time % 1.0) * width)
        segments = segments[offset : offset + width]
        return [Strip(segments, cell_length=width)]

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return container_width

    def get_height(self, rules: RulesMap, width: int) -> int:
        return 1


class Throbber(Widget):
    # The row is always reserved; only its paint and animation change.
    busy = reactive(False, layout=False)

    def on_mount(self) -> None:
        self.watch_busy(self.busy)

    def watch_busy(self, busy: bool) -> None:
        self.auto_refresh = 1 / 30 if busy and self.is_mounted else None

    def automatic_refresh(self) -> None:
        # Widget.is_on_screen falls back to the full geometry map for hidden
        # widgets. Scrolling invalidates that map, so an idle/hidden throbber
        # used to re-layout the whole transcript fifteen times per second.
        # Animation only needs the committed visible map; normal layout will
        # paint the indicator when it becomes visible again.
        if self.busy and self.is_attached:
            screen = self.screen
            try:
                current = self.app.screen
            except (ScreenStackError, UnknownModeError):
                # Mode removal/shutdown can retire the stack before this
                # widget's animation timer has been stopped.
                return
            if screen is current and self in screen._compositor.visible_widgets:
                self.refresh()

    def render(self) -> ThrobberVisual | str:
        return ThrobberVisual() if self.busy else ""
