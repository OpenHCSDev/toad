"""Fork dialog: create a child agent thread from the sidebar."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea
from agent_comms.channel_targets import Tag
from agent_comms.thread_management import ForkSpec
from agent_comms.threads import Thread


class ForkDialog(ModalScreen[ForkSpec]):
    """Collect one domain fork declaration, with editable inherited tags."""

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
    ForkDialog #fork-task { height: 6; }
    """

    BINDINGS = [("escape", "cancel"), ("ctrl+enter", "submit", "Fork")]

    def __init__(self, parent: Thread) -> None:
        super().__init__()
        self._parent_thread = parent

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(
                f"Fork from @{self._parent_thread.name}",
                id="title",
            )
            yield Static("Name")
            yield Input(placeholder="child-name", id="fork-name")
            yield Static("Task / goal / prompt (optional)")
            yield TextArea(id="fork-task")
            yield Static("Leave empty to start ready. Enter adds a line; Ctrl+Enter forks.")
            yield Static("Tags (comma-separated; edit to add or remove)")
            yield Input(", ".join(sorted(self._parent_thread.tags)), id="fork-tags")
            yield Static("", id="fork-error", markup=False)
            yield Button("Fork", id="fork-create", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#fork-name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_submit()

    def action_submit(self) -> None:
        name = self.query_one("#fork-name", Input).value.strip()
        if not name:
            self.query_one("#fork-error", Static).update("Enter a child name.")
            return
        try:
            tags = frozenset(Tag(value.strip()).name for value in
                             self.query_one("#fork-tags", Input).value.split(",") if value.strip())
            spec = ForkSpec(name=name, parent=self._parent_thread.name,
                            task=self.query_one("#fork-task", TextArea).text, tags=tags)
        except ValueError as error:
            self.query_one("#fork-error", Static).update(str(error))
            return
        self.dismiss(spec)

    def action_cancel(self) -> None:
        self.dismiss(None)
