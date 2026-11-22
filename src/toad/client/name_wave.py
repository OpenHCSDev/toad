"""A working thread waves through its own name, for every frontend.

Tristan, 2026-11-08: "replace the spinner with a colour/bold wave through the letters of
the thread or channel name". The effect is `ui_theme.effects.NAME_WAVE`, a `BandSweep` of
the accent crossing the line; its frames come from the app's one `AnimationClock`, so
every waving name on screen shows the same phase. What a line decides (being busy starts
the wave, idling stops it, the name is bold while it runs) and how a band's fractions
become cells of a line are declared here once: Textual's `ViewLabel` and backend, and
Qt's sidebar rows, tabs and row delegate, inherit them.
"""

from __future__ import annotations

from typing import ClassVar

from ui_theme.effects import NAME_WAVE, Band, Effect


class BandCells:
    """How a `Band` (fractions of a line) covers a line of `width` cells: each edge rounds
    to the nearest cell. Textual's colour backend and Qt's band painters read it here, so a
    band covers the same characters in both."""

    @staticmethod
    def band_cells(band: Band, width: int) -> tuple[int, int]:
        start, end = (max(0, min(width, round(edge * width))) for edge in (band.start, band.end))
        return start, max(start, end)


class NameWave(BandCells):
    """A line that waves through its name while its thread works. A plain parent: each
    frontend's line says how its effect runs (`wave_running`, `start_wave`, `stop_wave`)
    and paints the frame it reads."""

    name_wave: ClassVar[Effect[Band]] = NAME_WAVE
    painted_span: tuple[int, int] | None = None  # the band's cells as the line last drew them

    def wave_moved(self, span: tuple[int, int] | None) -> bool:
        """Whether a frame's band covers other cells than the line last drew. The band is
        drawn in whole cells, so a frame that leaves it on the same cells would paint the same
        line: on a busy bus about 40% of 660 sidebar row frames a second did (`qt_drive idle`)."""
        moved, self.painted_span = span != self.painted_span, span
        return moved

    def band_drawn(self) -> tuple[int, int] | None:
        """The band's cells as the line last decided to draw them (`wave_frame_drawn`), or
        none while it does not wave. What a paint draws: the band's place is worked out when
        the clock's frame arrives, which is what repaints the line, and not again to paint."""
        return self.painted_span if self.wave_running() else None

    def wave_span(self) -> tuple[int, int] | None:
        """The band's cells over this line now, or none while it does not wave. (Each line
        wrote the idle check itself, three times; a line answers only its cells.)"""
        return self.wave_cells() if self.wave_running() else None

    def wave_cells(self) -> tuple[int, int] | None:
        """The band's cells over this line while its wave runs, or none when it has no place
        to draw them (a line whose tree is gone)."""
        raise NotImplementedError

    def repaint_wave(self) -> None:
        """Paint the line this name occupies."""
        raise NotImplementedError

    def wave_frame_drawn(self) -> None:
        """One frame of the wave reached this line: it is painted when the band covers
        other cells than it last drew, and not otherwise. Every line that waves answers its
        clock here; a line that painted on each frame (Qt's tab title did, and the whole tab
        bar with it, 20 times a second for as long as a thread worked) redrew pixels that
        had not changed."""
        if self.wave_moved(self.wave_span()):
            self.repaint_wave()

    def wave_running(self) -> bool:
        raise NotImplementedError

    def start_wave(self) -> None:
        raise NotImplementedError

    def stop_wave(self) -> None:
        raise NotImplementedError

    def follow_activity(self, busy: bool) -> None:
        """Being busy is drawn, never spelled: it starts the wave without changing the text."""
        if busy:
            if not self.wave_running():
                self.painted_span = None  # its first frame draws: the name turns bold with it
                self.start_wave()
        else:
            self.painted_span = None
            self.stop_wave()

    def name_bold(self) -> bool:
        """The whole name is bold while the wave runs."""
        return self.wave_running()
