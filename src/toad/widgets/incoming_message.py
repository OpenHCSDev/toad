"""An attributed wire message with native thread navigation."""

from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.widgets import Markdown, Static

from toad.widgets.comms_sidebar import SelectTarget


class IncomingSender(Static, can_focus=True):
    BINDINGS = [("enter,space", "open_thread", "Open sender")]
    DEFAULT_CSS = """
    IncomingSender { height: auto; color: $accent; text-style: bold underline; }
    IncomingSender:hover, IncomingSender:focus { background: $accent 20%; }
    """

    def __init__(self, sender: str) -> None:
        self.sender = sender
        super().__init__(f"Incoming from {sender}:", markup=False)

    def action_open_thread(self) -> None:
        self.post_message(SelectTarget(self.sender, "thread"))

    def on_click(self, event: events.Click) -> None:
        if event.button == 1:
            event.stop()
            self.action_open_thread()


class IncomingMessage(VerticalGroup):
    DEFAULT_CLASSES = "block"

    def __init__(self, sender: str, text: str) -> None:
        super().__init__()
        self.sender = sender
        self.text = text

    def compose(self) -> ComposeResult:
        yield IncomingSender(self.sender)
        yield Markdown(self.text)

    def get_block_content(self, destination: str) -> str:
        return f"Incoming from {self.sender}:\n{self.text}"
