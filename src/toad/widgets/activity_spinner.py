"""Paint-only emphasis of Core's complete label in every busy thread view."""

from __future__ import annotations

from time import monotonic
from agent_comms.ui_model.sidebar import ThreadRowModel
from textual.content import Content
from typing import TYPE_CHECKING
from weakref import WeakSet

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.widgets.session_sidebar import ThreadStatusRow

PHASES = 10


def animated_label(row: ThreadRowModel, *, phase: int) -> Content:
    """Emphasize activity without replacing Core's marker, including warnings."""
    return Content.styled(row.label, "bold" if row.busy and phase < PHASES // 2 else "")


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
        return int(monotonic() * self.fps) % PHASES

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
