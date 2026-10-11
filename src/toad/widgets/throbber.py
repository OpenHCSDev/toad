from collections.abc import Callable
from functools import cached_property

from rich.segment import Segment

from textual.visual import Visual
from textual.app import ScreenStackError, UnknownModeError

from textual.style import Style
from textual.strip import Strip
from textual.visual import RenderOptions
from textual.widget import Widget
from textual.reactive import reactive
from textual.css.styles import RulesMap

from ui_theme.clock import Animation
from ui_theme.effects import ACTIVITY_SWEEP, Gradient


class ThrobberVisual(Visual):
    """The activity sweep: a band of theme colours moving across one row.

    `ui_theme.effects.ACTIVITY_SWEEP` says which colours and how fast; the
    app's colours backend paints the frame the animation shows now.
    """

    def __init__(self, throbber: Throbber, character: str = "━") -> None:
        self.throbber = throbber
        self.character = character

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions
    ) -> list[Strip]:
        throbber = self.throbber
        base = Strip([Segment(self.character * width, style.rich_style)], cell_length=width)
        animation = throbber.animation
        frame = animation.frame() if animation is not None else ACTIVITY_SWEEP.final
        return [throbber.app.colours.paint_gradient(frame, base)]

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return container_width

    def get_height(self, rules: RulesMap, width: int) -> int:
        return 1


class Throbber(Widget):
    # The row is always reserved; only its paint and animation change.
    busy = reactive(False, layout=False)

    animation: Animation[Gradient] | None = None

    @cached_property
    def _busy_visual(self) -> ThrobberVisual:
        # The animation's time and the theme's colours are read while
        # rendering; the gradient row stays warm in the colours backend.
        return ThrobberVisual(self)

    def on_mount(self) -> None:
        self.watch_busy(self.busy)

    def on_unmount(self) -> None:
        self.app.colours.clock.stop(self)
        self.animation = None

    def watch_busy(self, busy: bool) -> None:
        clock = self.app.colours.clock
        if busy and self.is_mounted:
            if self.animation is None:
                self.animation = clock.start(ACTIVITY_SWEEP, self)
        elif self.animation is not None:
            clock.stop(self)
            self.animation = None

    @property
    def animation_visible(self) -> bool:
        # Widget.is_on_screen falls back to the full geometry map for hidden
        # widgets. Scrolling invalidates that map, so an idle/hidden throbber
        # used to re-layout the whole transcript on every frame. Animation
        # only needs the committed visible map; normal layout paints the
        # indicator when it becomes visible again.
        if not (self.busy and self.is_attached):
            return False
        screen = self.screen
        try:
            current = self.app.screen
        except (ScreenStackError, UnknownModeError):
            # Mode removal/shutdown can retire the stack before the clock
            # has stopped this widget's animation.
            return False
        return screen is current and self in screen._compositor.visible_widgets

    def repaint(self) -> None:
        self.refresh()

    def render(self) -> ThrobberVisual | str:
        return self._busy_visual if self.busy else ""

    def _render_styles_sensitive(self) -> bool:
        # The visual measures only available width and one row.
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
