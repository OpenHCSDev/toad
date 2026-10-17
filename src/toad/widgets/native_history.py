"""Session source only: no controls and no decisions about input."""

from textual.reactive import var
from textual.widgets import Static

from toad.private_native_cursor import TOOLTIP, CursorStatus, HiddenCursorStatus


class NativeHistory(Static):
    DEFAULT_CSS = """
    NativeHistory { height: auto; padding: 0 1; color: $text-muted; }
    """
    status: var[type[CursorStatus]] = var(lambda: HiddenCursorStatus)

    def __init__(self) -> None:
        super().__init__("", markup=False)
        self.tooltip = TOOLTIP
        self.display = False

    def watch_status(self, status: type[CursorStatus]) -> None:
        self.display = status.visible
        self.update(status.label)
