from collections.abc import Callable
from functools import cached_property
from typing import ClassVar

from rich.segment import Segment
from textual import on
from textual.events import Mount
from textual.reactive import reactive
from textual.strip import Strip
from textual.style import Style
from textual.text_format import TextFormat
from textual.visual import RenderOptions, Visual
from ui_theme.effects import ACTIVITY_SWEEP, Ribbon
from ui_theme.scheme import BackgroundColour

from toad.frame_presentation import Animated, EffectInContent
from toad.native_style import FullWidth, OneRow
from toad.textual_colours import BlockInk, FullInk


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
        frame = throbber.effect_frame(throbber.effect)
        return [throbber.app.colours.paint_gradient(frame, base, edge=throbber.ink_edge)]

    def get_optimal_width(self, rules: TextFormat, container_width: int) -> int:
        return container_width

    def get_height(self, rules: TextFormat, width: int) -> int:
        return 1


class Throbber(EffectInContent, FullWidth, OneRow, Animated[Ribbon]):
    _paint_only_render = True
    tone = BackgroundColour
    """The sweep runs on the transcript's own background, not the band below it."""
    # The row is always reserved; only its paint and animation change.
    busy = reactive(False, layout=False)
    effect = ACTIVITY_SWEEP
    ink_edge: ClassVar[type[BlockInk]]

    @cached_property
    def _busy_visual(self) -> ThrobberVisual:
        # Glyph geometry belongs here; frame, colours and cadence stay in the
        # shared effect. A changing band never changes the reserved row.
        return ThrobberVisual(self)


    @on(Mount)
    def on_mount(self) -> None:
        self.watch_busy(self.busy)

    def watch_busy(self, busy: bool) -> None:
        # The activity owner's sync changes animation ownership and retires its paint.
        if busy and self.is_mounted:
            if self.effect not in self.effects:
                self.run_effect(self.effect)
        else:
            self.stop_effect(self.effect)
        self.refresh()

    def render(self) -> ThrobberVisual | str:
        return self._busy_visual if self.busy else ""


class ObservedThrobber(Throbber):
    """Paint an existing activity owner without a writable busy mirror."""

    def __init__(self, read_busy: Callable[[], bool], **kwargs) -> None:
        super().__init__(**kwargs)
        self._read_busy = read_busy

    def compute_busy(self) -> bool:
        return self._read_busy()

    def sync(self) -> None:
        """Read the activity owner again, and let the reactive do the rest.

        `busy` is computed, so it recomputes when it is read and invokes its own watcher
        if the answer changed (textual `reactive.py:170`). Calling the watcher by hand as
        well ran it twice for every source round: a phone capture of a landing page with
        no input recorded 238 `watch_busy` invocations for 60 hidden source rounds, each
        one ending in a `refresh()` of a throbber that renders nothing when it is not
        busy, on a view nobody was looking at.

        Unlike `on_mount`, this has nothing of its own to say: mounting changes whether
        the effect may run without `busy` changing, while a sync only asks the question
        again.
        """
        # The read *is* the recompute; it is bound to a name only because a bare
        # attribute read looks like a mistake and lints as one.
        _recomputed = self.busy


class AboveThrobber(ObservedThrobber):
    """The bar above the status, in whole blocks."""

    ink_edge = FullInk
