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

    from toad.screens.session_view import SessionView


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
    It waits for that session's messages to be ready, then shows only if the
    session is still the one shown; nothing about a choice outlives it.
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
        # The session whose messages it was last shown over; read only while it shows.
        self.over: SessionView | None = None
        self.display = False

    def on_mount(self) -> None:
        self.observe_core(self.app.events)
        self._layout_screen = self.screen
        self._layout_screen.screen_layout_refresh_signal.subscribe(self, self.refit)

    def on_unmount(self) -> None:
        self._layout_screen.screen_layout_refresh_signal.unsubscribe(self)

    @handles(core_events.SessionSelected)
    def session_selected(self, event: core_events.SessionSelected) -> None:
        """Every choice retires the name over the departing view; a workspace session (DM or
        channel) names itself once its messages are ready. The store has no session view."""
        self.retire()
        if (view := self.app.workspace_sessions.views.get(event.mode_name)) is not None:
            # Exclusive: a later choice cancels this wait. A view whose content failed
            # shows its own failure and gets no name over it.
            self.run_worker(self.show_ready(view, event.mode_name), group="switch-toast",
                            exclusive=True, exit_on_error=False)

    async def show_ready(self, view: SessionView, mode_name: str) -> None:
        await view.wait_content_ready()
        if not self.app.workspace_sessions.source.shown(view):
            return
        titles = {tab.mode_name: tab.title for tab in self.app.open_tabs}
        if mode_name in titles and (area := self.viewport(view)) is not None:
            self.over = view
            self.show(titles[mode_name], area)

    @classmethod
    def framed(cls, name_width: int, name_rows: int) -> tuple[int, int]:
        """The toast's size around a name of that many cells and rows: its margin, then its frame."""
        rows, columns = cls.MARGIN
        return name_width + 2 * columns + 2, name_rows + 2 * rows + 2

    @staticmethod
    def room(area: Region) -> int:
        """The widest the toast may be in a viewport: the viewport less a margin each side."""
        return max(0, area.width - 4)

    @classmethod
    def holds(cls, area: Region, name_width: int, name_rows: int) -> bool:
        """Whether that viewport contains the framed name whole."""
        width, height = cls.framed(name_width, name_rows)
        return width <= cls.room(area) and height <= area.height

    @property
    def box(self) -> tuple[int, int]:
        width, height = self.framed(max(map(cell_len, self.lines)), len(self.lines))
        return min(width, self.room(self.area)), height

    def viewport(self, view: SessionView) -> Region | None:
        """The view's scrolling message viewport in screen cells; none without a conversation,
        or when it cannot contain even a one-cell, one-row framed name."""
        region = view.message_region()
        return region if region is not None and self.holds(region, 1, 1) else None

    def show(self, title: str, area: Region) -> None:
        self.title = title
        self.fit(area)
        self.display = True
        self.run_effect(TAB_TOAST)
        self.refresh(layout=True)

    def retire(self) -> None:
        """No conversation, or one too small for the framed name: no name stays over another view."""
        self.stop_effect(TAB_TOAST)
        self.display = False

    def fit(self, area: Region) -> bool:
        """Fit and centre the name in the message viewport; whether its place or size changed."""
        self.area = area
        large = LargeText.rows(self.title)
        fits = self.holds(area, LargeText.width(self.title), len(large))
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
        if not self.app.workspace_sessions.source.shown(self.over) or (
                area := self.viewport(self.over)) is None:
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
