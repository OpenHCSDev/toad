from collections.abc import Callable
from functools import cached_property

from rich.segment import Segment

from textual.visual import Visual

from textual.style import Style
from textual.strip import Strip
from textual.visual import RenderOptions
from textual.widget import Widget
from textual.reactive import reactive
from textual.css.styles import RulesMap

from ui_theme.effects import ACTIVITY_SWEEP

from toad.textual_colours import Animated


class ThrobberVisual(Visual):
    """The activity sweep: a band of theme colours moving across one row.

    `ui_theme.effects.ACTIVITY_SWEEP` says which colours and how fast; the
    app's colours backend paints the frame the animation shows now.
    """

    def __init__(self, throbber: Throbber) -> None:
        self.throbber = throbber

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions
    ) -> list[Strip]:
        throbber = self.throbber
        base = Strip([Segment("█" * width, style.rich_style)], cell_length=width)
        animation = throbber.animation
        frame = animation.frame() if animation is not None else throbber.effect.final
        return [frame.paint(throbber.app.colours, base)]

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return container_width

    def get_height(self, rules: RulesMap, width: int) -> int:
        return 1


class Throbber(Animated, Widget):
    # The row is always reserved; only its paint and animation change.
    busy = reactive(False, layout=False)

    def __init__(self, *, thickness: float = 0.375, **kwargs) -> None:
        super().__init__(**kwargs)
        self.effect = ACTIVITY_SWEEP.scaled(thickness)

    @cached_property
    def _busy_visual(self) -> ThrobberVisual:
        # Glyph geometry belongs here; frame, colours and cadence stay in the
        # shared effect. A changing band never changes the reserved row.
        return ThrobberVisual(self)

    def on_mount(self) -> None:
        self.watch_busy(self.busy)

    def watch_busy(self, busy: bool) -> None:
        # A computed busy changes when it is read, often by the clock's tick,
        # which repaints only visible running animations: repaint here so the
        # last sweep frame never stays on screen once work ends.
        if busy and self.is_mounted:
            if self.animation is None:
                self.run_effect(self.effect)
        else:
            self.stop_effect()
        self.refresh()

    @property
    def animation_visible(self) -> bool:
        return self.busy and super().animation_visible

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
