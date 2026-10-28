"""The name of the tab just chosen, large and centred over the workspace, fading in and out."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metaclass_registry.mro_dispatch import handles
from rich.cells import cell_len, set_cell_size
from rich.segment import Segment
from rich.style import Style
from textual.geometry import Offset
from textual.strip import Strip
from textual.css.scalar import Scalar
from ui_theme.effects import Amount, Effect
from ui_theme.scheme import AccentColour, BackgroundColour, ForegroundColour, HeaderToneColour

from toad.core import events as core_events
from toad.core_event_carrier import CoreEventReceiver
from toad.frame_presentation import Animated
from toad.widget_view import WidgetView

if TYPE_CHECKING:
    from textual._paint_state import PaintState


@dataclass(frozen=True)
class Swell(Effect[Amount]):
    """Rises to full, holds, then falls back to nothing; it ends at nothing."""

    rise: float
    hold: float
    fall: float
    frames_per_second: float

    @property
    def duration(self) -> float:  # type: ignore[override]
        return self.rise + self.hold + self.fall

    def frame(self, elapsed: float) -> Amount:
        rising = self.ease_out(self.progress(elapsed, self.rise))
        falling = self.ease_out(self.progress(self.duration - elapsed, self.fall))
        return Amount(min(rising, falling))

    @property
    def final(self) -> Amount:
        return Amount(0.0)


TAB_TOAST = Swell(rise=0.12, hold=0.5, fall=0.35, frames_per_second=30)


class SwitchToast(CoreEventReceiver, WidgetView, Animated[Amount]):
    """The chosen tab's name, so the reader sees where they landed without finding the tab.

    It never takes focus or pointer input: clicks pass to what is under it.
    A new choice while it shows replaces its name and restarts its swell.
    It is laid out only when it appears and when it ends; every frame between
    repaints its own few rows.
    """

    can_focus = False
    hit_test_transparent = True
    position = "absolute"
    overlay = "screen"
    # Cells around the name, inside the frame.
    MARGIN = (1, 6)

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.display = False

    def on_mount(self) -> None:
        self.observe_core(self.app.events)

    @handles(core_events.SessionSelected)
    def session_selected(self, event: core_events.SessionSelected) -> None:
        tabs = {tab.mode_name: tab for tab in self.app.open_tabs}
        if (tab := tabs.get(event.mode_name)) is not None:
            self.show(tab.title)

    @property
    def box(self) -> tuple[int, int]:
        rows, columns = self.MARGIN
        width = min(cell_len(self.title) + 2 * columns + 2, max(0, self.screen.size.width - 4))
        return width, 2 * rows + 3

    def show(self, title: str) -> None:
        self.title = title
        width, height = self.box
        self.width, self.height = Scalar.from_number(width), Scalar.from_number(height)
        screen = self.screen.size
        self.absolute_offset = Offset((screen.width - width) // 2, (screen.height - height) // 2)
        self.display = True
        self.run_effect(TAB_TOAST)
        self.refresh(layout=True)

    def on_show(self) -> None:
        super().on_show()
        self.repaint()

    def repaint(self) -> None:
        """The clock's paint request: the toast leaves the layout once its swell ends."""
        self.display = self.effect_phase(TAB_TOAST).in_motion
        self.refresh()

    def render_line(self, y: int, paint: PaintState) -> Strip:
        colours = self.app.colours
        amount = self.effect_frame(TAB_TOAST).value
        background = colours.mixed(BackgroundColour, HeaderToneColour, amount).rich_color
        frame = Style(color=colours.mixed(BackgroundColour, AccentColour, amount).rich_color, bgcolor=background)
        name = Style(color=colours.mixed(BackgroundColour, ForegroundColour, amount).rich_color,
                     bgcolor=background, bold=True)
        width, height = self.box
        inner = max(0, width - 2)
        if y == 0 or y == height - 1:
            left, right = ("╭", "╮") if y == 0 else ("╰", "╯")
            return Strip([Segment(left + "─" * inner + right, frame)], width)
        text = self.title if y == height // 2 else ""
        if cell_len(text) > inner:
            text = set_cell_size(text, max(0, inner - 1)) + "…"
        padding = inner - cell_len(text)
        return Strip([Segment("│", frame),
                      Segment(" " * (padding // 2) + text + " " * (padding - padding // 2), name),
                      Segment("│", frame)], width)
