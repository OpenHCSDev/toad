"""Session provenance only: no controls or input-disposition semantics."""

from textual.reactive import var
from textual.widgets import Static

from toad.private_native_cursor import LABELS, TOOLTIP, CursorStatus


class NativeHistory(Static):
    DEFAULT_CSS = """
    NativeHistory { height: auto; padding: 0 1; color: $text-muted; }
    """
    status: var[CursorStatus | None] = var(None)

    def __init__(self) -> None:
        super().__init__("", markup=False)
        self.tooltip = TOOLTIP
        self.display = False

    def watch_status(self, status: CursorStatus | None) -> None:
        self.display = status is not None
        self.update(LABELS.get(status, LABELS["unavailable"]) if status else "")
