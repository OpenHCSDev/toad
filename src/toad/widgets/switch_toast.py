"""The name of the tab just chosen, large and centred over its messages, fading in and out."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metaclass_registry.mro_dispatch import handles
from rich.cells import cell_len, set_cell_size
from rich.segment import Segment
from rich.style import Style
from textual.geometry import Region
from textual.strip import Strip
from ui_theme.effects import Amount, Effect
from ui_theme.scheme import (
    AccentColour,
    BackgroundColour,
    ForegroundColour,
    HeaderToneColour,
)

from toad.core import events as core_events
from toad.core_event_carrier import CoreEventReceiver
from toad.frame_presentation import Animated
from toad.large_text import LargeText
from toad.app_node import ToadNode

if TYPE_CHECKING:
    from textual._paint_state import PaintState
    from textual.screen import Screen


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


class SwitchToast(CoreEventReceiver, Animated[Amount], ToadNode):
    """The chosen tab's name, so the reader sees where they landed without finding the tab.

    It never takes focus or pointer input: clicks pass to what is under it.
    A new choice while it shows replaces its name and restarts its swell.
    It is centred over the scrolling message viewport of the shown session,
    not the terminal: sidebars, header, footer and prompt are outside it.
    It is laid out only when it appears, when a layout moves that viewport
    while it shows, and when it ends; every frame between repaints its own
    few rows.
    """

    DEFAULT_CSS = "SwitchToast { position: absolute; overlay: screen; }"
    can_focus = False
    hit_test_transparent = True
    # Cells around the name, inside the frame.
    MARGIN = (1, 6)

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        # The name as drawn: three rows tall when that fits the viewport, else one.
        self.lines: tuple[str, ...] = ()
        # The message viewport it was last fitted to, and where it sits in it, in screen cells.
        self.area = self.placed = Region()
        self.display = False

    def on_mount(self) -> None:
        self.observe_core(self.app.events)
        self._layout_screen = self.screen
        self._layout_screen.screen_layout_refresh_signal.subscribe(self, self.refit)

    def on_unmount(self) -> None:
        self._layout_screen.screen_layout_refresh_signal.unsubscribe(self)

    @handles(core_events.SessionSelected)
    def session_selected(self, event: core_events.SessionSelected) -> None:
        titles = {tab.mode_name: tab.title for tab in self.app.open_tabs}
        if event.mode_name in titles:
            self.show(titles[event.mode_name])

    @property
    def box(self) -> tuple[int, int]:
        rows, columns = self.MARGIN
        width = min(max(map(cell_len, self.lines)) + 2 * columns + 2, self.room)
        return width, len(self.lines) + 2 * rows + 2

    @property
    def room(self) -> int:
        """The widest the toast may be: the message viewport less a margin each side."""
        return max(0, self.area.width - 4)

    def viewport(self) -> Region | None:
        """The shown session's scrolling message viewport in screen cells; none without a native reader."""
        conversation = self.app.workspace_chrome.native.widget
        if conversation is None or not conversation.is_mounted:
            return None
        region = conversation.window.scrollable_content_region
        return region if region.area else None

    def show(self, title: str) -> None:
        self.title = title
        if (area := self.viewport()) is None:
            self.retire()
            return
        self.fit(area)
        self.display = True
        self.run_effect(TAB_TOAST)
        self.refresh(layout=True)

    def retire(self) -> None:
        """No native reader is shown: no name stays over another view."""
        self.stop_effect(TAB_TOAST)
        self.display = False

    def fit(self, area: Region) -> bool:
        """Fit and centre the name in the message viewport; whether its place or size changed."""
        self.area = area
        large = LargeText.rows(self.title)
        rows, columns = self.MARGIN
        fits = (LargeText.width(self.title) + 2 * columns + 2 <= self.room
                and len(large) + 2 * rows + 2 <= area.height)
        self.lines = large if fits else (self.title,)
        width, height = self.box
        placed = Region(area.x + (area.width - width) // 2,
                        area.y + (area.height - height) // 2, width, height)
        moved, self.placed = placed != self.placed, placed
        self.styles.width, self.styles.height = width, height
        self.absolute_offset = placed.offset
        return moved

    def refit(self, _screen: Screen) -> None:
        """A layout that moves the viewport while the name shows refits it, without restarting its swell."""
        if not self.display:
            return
        if (area := self.viewport()) is None:
            self.retire()
        elif self.fit(area):
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
        background = colours.mixed(
            BackgroundColour, HeaderToneColour, amount
        ).rich_color
        frame = Style(
            color=colours.mixed(BackgroundColour, AccentColour, amount).rich_color,
            bgcolor=background,
        )
        name = Style(
            color=colours.mixed(BackgroundColour, ForegroundColour, amount).rich_color,
            bgcolor=background,
            bold=True,
        )
        width, height = self.box
        inner = max(0, width - 2)
        if y == 0 or y == height - 1:
            left, right = ("╭", "╮") if y == 0 else ("╰", "╯")
            return Strip([Segment(left + "─" * inner + right, frame)], width)
        line = y - 1 - self.MARGIN[0]
        text = self.lines[line] if 0 <= line < len(self.lines) else ""
        if cell_len(text) > inner:
            text = set_cell_size(text, max(0, inner - 1)) + "…"
        padding = inner - cell_len(text)
        return Strip(
            [
                Segment("│", frame),
                Segment(
                    " " * (padding // 2) + text + " " * (padding - padding // 2), name
                ),
                Segment("│", frame),
            ],
            width,
        )
