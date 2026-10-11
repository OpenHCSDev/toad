from collections.abc import Callable, Mapping
from functools import cached_property, lru_cache
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

from toad.effects import ACTIVITY_SWEEP, GradientSweep


class ThrobberVisual(Visual):
    """The activity sweep: a band of theme colours moving across one row.

    `toad.effects.ACTIVITY_SWEEP` says which colours and how fast; this paints
    it. The row for a width and set of colours is built once and sliced by time.
    """

    def __init__(
        self, get_variables: Callable[[], Mapping[str, str]], sweep: GradientSweep = ACTIVITY_SWEEP,
        character: str = "━", get_time: Callable[[], float] = monotonic,
    ) -> None:
        self.sweep = sweep
        self.get_variables = get_variables
        self.character = character
        self.get_time = get_time

    @lru_cache(maxsize=8)
    def make_segments(self, style: Style, width: int, stops: tuple[str, ...]) -> list[Segment]:
        """Two widths of the gradient, so any window of `width` cells is a slice."""
        background = style.rich_style.bgcolor
        character = self.character
        colours = [Color.parse(stop) for stop in stops]
        count = len(colours)
        # ANSI colours cannot be blended; they step from one stop to the next.
        blend = all(colour.ansi is None for colour in colours)
        segments = []
        for offset in range(width * 2):
            position = offset * count / max(width, 1)
            index = int(position) % count
            colour = colours[index]
            if blend:
                colour = colour.blend(colours[(index + 1) % count], position - int(position))
            segments.append(Segment(character, RichStyle.from_color(colour.rich_color, background)))
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
        variables = self.get_variables()
        stops = tuple(variables[stop.declared_name] for stop in self.sweep.stops)
        segments = self.make_segments(style, width, stops)
        offset = width - self.sweep.shift(self.get_time(), width)
        segments = segments[offset : offset + width]
        return [Strip(segments, cell_length=width)]

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return container_width

    def get_height(self, rules: RulesMap, width: int) -> int:
        return 1


class Throbber(Widget):
    # The row is always reserved; only its paint and animation change.
    busy = reactive(False, layout=False)

    # The sweep's own cadence. Tying it to the app's frame cap (144 Hz)
    # repainted a full-width row every frame while an agent worked.
    ANIMATION_INTERVAL = 1 / ACTIVITY_SWEEP.frames_per_second

    @cached_property
    def _busy_visual(self) -> ThrobberVisual:
        # Animation time and the theme's colours are read while rendering. Keep
        # the gradient table warm across repaint invalidations instead of
        # caching fresh Visual IDs.
        return ThrobberVisual(lambda: self.app.theme_variables)

    def on_mount(self) -> None:
        self.watch_busy(self.busy)

    def watch_busy(self, busy: bool) -> None:
        interval = self.ANIMATION_INTERVAL if busy and self.is_mounted else None
        if self.auto_refresh != interval:
            self.auto_refresh = interval

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
        return self._busy_visual if self.busy else ""

    def _render_styles_sensitive(self) -> bool:
        # The original visual measures only available width and one row.
        # Paint rules affect its segments; custom renderers retain the native
        # conservative contract rather than inheriting a fixed-shape claim.
        return (
            type(self).render is not Throbber.render
            or type(self)._render is not Widget._render
            or type(self)._busy_visual is not Throbber._busy_visual
        )


class ObservedThrobber(Throbber):
    """Paint an existing activity owner without a writable busy mirror."""

    def __init__(self, read_busy: Callable[[], bool], **kwargs) -> None:
        super().__init__(**kwargs)
        self._read_busy = read_busy

    def compute_busy(self) -> bool:
        return self._read_busy()

    def sync(self) -> None:
        self.watch_busy(self.busy)
        self.refresh()
