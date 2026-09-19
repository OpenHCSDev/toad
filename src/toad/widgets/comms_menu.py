"""Right-click context menus for the comms sidebar."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class _Menu(ModalScreen[str]):
    """Minimal popup menu: returns the chosen action id."""

    DEFAULT_CSS = """
    _Menu {
        align: center middle;
        background: $background 40%;
    }
    _Menu #items {
        width: 34;
        background: $surface;
        border: solid $primary;
        padding: 0 1;
    }
    _Menu .item {
        height: 1;
        padding: 0 1;
    }
    _Menu .item:hover {
        background: $accent;
        color: $text;
    }
    _Menu .title {
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [("escape", "cancel")]

    def __init__(self, title: str, items: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._items = items

    def compose(self) -> ComposeResult:
        with Vertical(id="items"):
            yield Static(self._title, classes="title")
            for action_id, label in self._items:
                yield Static(label, classes="item", id=f"item-{action_id}")

    def on_click(self, event) -> None:
        widget = self.screen.get_widget_at(event.screen_x, event.screen_y)
        if widget is None:
            return
        if widget.id and widget.id.startswith("item-"):
            self.dismiss(widget.id[len("item-") :])
        elif widget.id == "items":
            self.dismiss("")
        else:
            self.dismiss("")

    def action_cancel(self) -> None:
        self.dismiss("")


def _show(screen, title: str, items: list[tuple[str, str]], actions: dict) -> None:
    """Push a menu; route the chosen action id to its callable."""

    def handle(choice: str) -> None:
        if choice and choice in actions:
            actions[choice]()

    screen.app.push_screen(_Menu(title, items), callback=handle)


def show_thread_menu(screen, name: str, actions: dict) -> None:
    _show(
        screen,
        f"@{name}",
        [
            ("fork", "Fork from this thread"),
            ("ack", "Mark inbox read"),
            ("copy", "Copy name"),
        ],
        actions,
    )


def show_channel_menu(screen, name: str, actions: dict) -> None:
    _show(
        screen,
        name,
        [
            ("ack", "Mark read"),
            ("copy", "Copy name"),
        ],
        actions,
    )
