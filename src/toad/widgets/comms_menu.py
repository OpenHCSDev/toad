"""Pointer-anchored desktop context menus for the comms sidebar."""

from __future__ import annotations

from collections.abc import Callable

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.dom import DOMNode
from textual.geometry import Offset, clamp
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class ContextMenuItem(Static, can_focus=True):
    """A menu item with desktop-style press and release behavior."""

    class Pressed(Message):
        def __init__(self, item: ContextMenuItem) -> None:
            self.item = item
            super().__init__()

    def __init__(self, action: str, label: str) -> None:
        super().__init__(label, classes="item")
        self.action = action
        self._pressed = False

    @property
    def allow_select(self) -> bool:
        return False

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 1:
            self._pressed = True
            self.add_class("-pressed")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.remove_class("-pressed")
        if event.button == 1 and self._pressed:
            self._pressed = False
            self.post_message(self.Pressed(self))

    def on_leave(self) -> None:
        self._pressed = False
        self.remove_class("-pressed")


class ContextMenu(ModalScreen[str]):
    """A transparent modal with a menu anchored to a screen coordinate.

    The interaction pattern follows trissim/textual-window's WindowBarMenu:
    the modal owns dismissal while the small menu container is positioned at
    the pointer and clamped inside the terminal viewport.
    """

    CSS = """
    ContextMenu {
        align: left top;
        background: transparent;
    }
    ContextMenu #context-menu {
        width: auto;
        height: auto;
        background: $background;
        border: solid $primary;
        padding: 0;
    }
    ContextMenu .title {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $background;
        text-style: bold reverse;
    }
    ContextMenu .item {
        height: 1;
        padding: 0 1;
    }
    ContextMenu .item:hover,
    ContextMenu .item:focus {
        background: $accent;
        color: $background;
        text-style: bold;
    }
    ContextMenu .item.-pressed {
        background: $primary;
        color: $background;
    }
    ContextMenu:ansi .item:hover,
    ContextMenu:ansi .item:focus,
    ContextMenu:ansi .item.-pressed {
        background: ansi_default;
        color: ansi_default;
        text-style: bold reverse;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("up", "previous", show=False),
        Binding("down", "next", show=False),
        Binding("enter", "choose", show=False),
    ]

    def __init__(
        self,
        menu_offset: Offset,
        title: str,
        items: list[tuple[str, str]],
    ) -> None:
        super().__init__()
        self.menu_offset = menu_offset
        self._title = title
        self._items = items

    def compose(self) -> ComposeResult:
        with Container(id="context-menu"):
            yield Static(self._title, classes="title")
            for action, label in self._items:
                yield ContextMenuItem(action, label)

    def on_mount(self) -> None:
        menu = self.query_one("#context-menu", Container)
        menu_width = (
            max(len(self._title), *(len(label) for _, label in self._items)) + 4
        )
        menu_width = min(menu_width, self.size.width)
        menu_height = len(self._items) + 3
        x = int(clamp(self.menu_offset.x, 0, max(0, self.size.width - menu_width)))
        y = int(clamp(self.menu_offset.y, 0, max(0, self.size.height - menu_height)))
        menu.styles.width = menu_width
        menu.offset = Offset(x, y)
        items = list(self.query(ContextMenuItem))
        if items:
            items[0].focus()

    def _menu_items(self) -> list[ContextMenuItem]:
        return list(self.query(ContextMenuItem))

    def action_previous(self) -> None:
        items = self._menu_items()
        if not items:
            return
        focused = self.focused
        index = items.index(focused) if focused in items else 0
        items[(index - 1) % len(items)].focus()

    def action_next(self) -> None:
        items = self._menu_items()
        if not items:
            return
        focused = self.focused
        index = items.index(focused) if focused in items else -1
        items[(index + 1) % len(items)].focus()

    def action_choose(self) -> None:
        if isinstance(self.focused, ContextMenuItem):
            self.dismiss(self.focused.action)

    def action_cancel(self) -> None:
        self.dismiss("")

    @on(ContextMenuItem.Pressed)
    def item_pressed(self, event: ContextMenuItem.Pressed) -> None:
        event.stop()
        self.dismiss(event.item.action)

    def on_click(self, event: events.Click) -> None:
        widget, _ = self.get_widget_at(event.screen_x, event.screen_y)
        node: DOMNode | None = widget
        while node is not None:
            if node.id == "context-menu":
                return
            node = node.parent
        self.dismiss("")


class RenameSessionDialog(ModalScreen[str | None]):
    """Small name editor used from a local session row."""

    CSS = """
    RenameSessionDialog {
        align: center middle;
        background: $background 40%;
    }
    RenameSessionDialog #rename-session {
        width: 48;
        height: auto;
        padding: 1;
        border: solid $primary;
        background: $background;
    }
    RenameSessionDialog Static { height: 1; margin-bottom: 1; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current_name: str) -> None:
        super().__init__()
        self.current_name = current_name

    def compose(self) -> ComposeResult:
        with Container(id="rename-session"):
            yield Static("Rename session")
            yield Input(self.current_name, select_on_focus=True, compact=True)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    def submit_name(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if name:
            self.dismiss(name)

    def action_cancel(self) -> None:
        self.dismiss(None)


def _show(
    screen,
    menu_offset: Offset,
    title: str,
    items: list[tuple[str, str]],
    actions: dict[str, Callable[[], None]],
) -> None:
    """Push an anchored menu and route its selected action."""

    def handle(choice: str) -> None:
        if choice and choice in actions:
            actions[choice]()

    screen.app.push_screen(
        ContextMenu(menu_offset, title, items),
        callback=handle,
    )


def show_thread_menu(
    screen,
    menu_offset: Offset,
    name: str,
    items: list[tuple[str, str]],
    actions: dict[str, Callable[[], None]],
) -> None:
    _show(
        screen,
        menu_offset,
        f"@{name}",
        items,
        actions,
    )


def show_session_menu(
    screen,
    menu_offset: Offset,
    title: str,
    actions: dict[str, Callable[[], None]],
    *,
    is_agent_session: bool,
) -> None:
    items = (
        [
            ("rename", "Rename session"),
            ("archive", "Archive session"),
            ("delete", "Delete saved session"),
        ]
        if is_agent_session
        else [("archive", "Close view")]
    )
    _show(
        screen,
        menu_offset,
        title,
        items,
        actions,
    )


def show_channel_menu(
    screen,
    menu_offset: Offset,
    name: str,
    actions: dict[str, Callable[[], None]],
    *,
    acknowledge_label: str,
) -> None:
    _show(
        screen,
        menu_offset,
        name,
        [
            ("comms_ack", acknowledge_label),
            ("copy", "Copy name"),
        ],
        actions,
    )
