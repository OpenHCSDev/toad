"""Pointer menus use the native modal screen's result and focus lifetime."""
from __future__ import annotations

from collections.abc import Callable
from typing import cast

from textual import events, on
from textual.binding import Binding
from textual.color import TRANSPARENT
from textual.css._style_properties import Edges
from textual.geometry import Offset
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from ui_theme.scheme import BackgroundColour, ForegroundColour, PrimaryColour
from toad.screens.modal import ModalScreen
from toad.widget_view import AUTO, FILL, WidgetView


class ContextMenuItem[Choice](Option):
    def __init__(self, action: Choice, label: str) -> None:
        super().__init__(label)
        self.action = action


class ContextMenuOptions[Choice](WidgetView, OptionList):
    """The native list owns the anchored rows and their theme paint."""

    width = height = AUTO
    position = "absolute"
    overlay = "screen"
    constrain_x = constrain_y = "inside"
    vertical_scrollbar_size = horizontal_scrollbar_size = 0

    def __init__(self, menu_offset: Offset, title: str, items) -> None:
        super().__init__(*(ContextMenuItem(action, label) for action, label in items))
        self.border_title = title
        self.absolute_offset = menu_offset
        self.highlighted = 0 if self.option_count else None

    @property
    def border(self):
        return Edges(*(("solid", self.app.colours.colour(PrimaryColour)),) * 4)

    @property
    def paint_background(self):
        return self.app.colours.colour(BackgroundColour)

    @property
    def paint_foreground(self):
        return self.app.colours.colour(ForegroundColour)


class ContextMenu[Choice](WidgetView, ModalScreen[Choice]):
    """Native dismissal owns Escape, selection, results and focus restoration."""

    width = height = FILL
    paint_background = TRANSPARENT
    BINDINGS = [Binding("escape", "dismiss", show=False)]

    def __init__(self, menu_offset: Offset, title: str, items) -> None:
        super().__init__()
        self.options = ContextMenuOptions[Choice](menu_offset, title, items)

    def compose(self):
        yield self.options

    @classmethod
    def show(cls, screen, menu_offset: Offset, title: str, items, *, callback):
        menu = cls(menu_offset, title, items)
        screen.app.push_screen(menu, callback)
        return menu

    @classmethod
    async def choose(cls, screen, menu_offset: Offset, title: str, items):
        return await screen.app.push_screen_wait(cls(menu_offset, title, items))

    @on(OptionList.OptionSelected)
    def item_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(cast(ContextMenuItem[Choice], event.option).action)

    def on_click(self, event: events.Click) -> None:
        if not self.options.region.contains(*event.screen_offset):
            event.stop()
            self.dismiss(None)


def show_target_menu(
    screen,
    menu_offset: Offset,
    title: str,
    items: list[tuple[str, str]],
    actions: dict[str, Callable[[], None]],
) -> None:
    """Use the same modal menu for contextual declarations."""
    def handle(choice: str | None) -> None:
        if choice and choice in actions:
            actions[choice]()

    ContextMenu.show(screen, menu_offset, title, items, callback=handle)
