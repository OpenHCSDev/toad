"""Session source only: no controls and no decisions about input."""

from textual.reactive import var
from textual.widgets import Static

from toad.native_style import MutedText, SidePadding
from toad.private_native_cursor import TOOLTIP, CursorStatus, HiddenCursorStatus


class NativeHistory(MutedText, SidePadding, Static):
    status: var[type[CursorStatus]] = var(lambda: HiddenCursorStatus)


    def __init__(self) -> None:
        super().__init__("", markup=False)
        self.tooltip = TOOLTIP
        self.display = False

    def watch_status(self, status: type[CursorStatus]) -> None:
        self.display = status.visible
        self.update(status.label)
