"""Fork dialog: create a child agent thread from the sidebar."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class ForkDialog(ModalScreen[tuple[str, str]]):
    """Ask for child name and task; returns (name, task) or None."""

    DEFAULT_CSS = """
    ForkDialog {
        align: center middle;
        background: $background 40%;
    }
    ForkDialog #box {
        width: 60;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    """

    BINDINGS = [("escape", "cancel")]

    def __init__(self, parent: str) -> None:
        super().__init__()
        self._parent = parent

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(f"Fork from @{self._parent} — child name and task:", id="title")
            yield Input(placeholder="child-name fix the flake in the viewer", id="fork-input")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        parts = value.split(maxsplit=1)
        if len(parts) != 2:
            self.query_one("#title", Static).update("need: child-name task (esc to cancel)")
            return
        self.dismiss((parts[0], parts[1]))

    def action_cancel(self) -> None:
        self.dismiss(None)
