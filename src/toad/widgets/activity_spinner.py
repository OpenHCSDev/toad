"""One-cell paint-only replacement for busy hourglass markers in Toad views."""

from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING
from weakref import WeakSet

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.widgets.session_sidebar import ThreadStatusRow

FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def animated_label(label: str, *, busy: bool, phase: int) -> str:
    if not busy:
        return label
    for marker in ("⌛ ", "● "):
        if label.startswith(marker):
            return f"{FRAMES[phase % len(FRAMES)]} {label[len(marker):]}"
    return label


class BusyRows:
    """The spinner frame is a function of time; one app timer repaints visible busy rows."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.rows: WeakSet[ThreadStatusRow] = WeakSet()
        self.timer = None

    @property
    def fps(self) -> int:
        return self.app.settings.sidebar.spinner_frames_per_second

    @property
    def phase(self) -> int:
        return int(monotonic() * self.fps) % len(FRAMES)

    def track(self, row: ThreadStatusRow, busy: bool) -> None:
        if busy:
            self.rows.add(row)
            if self.timer is None:
                self.timer = self.app.set_interval(1 / self.fps, self.tick)
            else:
                self.timer.resume()
        else:
            self.rows.discard(row)
            if not self.rows and self.timer is not None:
                self.timer.pause()

    def cadence_changed(self) -> None:
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        if self.rows:
            self.timer = self.app.set_interval(1 / self.fps, self.tick)

    def tick(self) -> None:
        for row in tuple(self.rows):
            if row.is_attached and row.screen.is_current and row in row.screen._compositor.visible_widgets:
                row.paint()
