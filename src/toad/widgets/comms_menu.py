"""Pointer menus use the native modal screen's result and focus lifetime."""
from __future__ import annotations

from collections.abc import Callable
from typing import cast

from textual import events, on
from textual.view import (
    AUTO,
    FILL,
    WidgetView,
)
from toad.widget_actions import HiddenActions
from textual.color import TRANSPARENT
from textual.css._style_properties import Edges
from textual.geometry import Region, Spacing
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from ui_theme.scheme import BackgroundColour, ForegroundColour, PrimaryColour
from toad.screens.modal import DismissibleScreen
from textual import on


class ContextMenuItem[Choice](Option):
    def __init__(self, action: Choice, label: str) -> None:
        super().__init__(label)
        self.action = action


class ContextMenuOptions[Choice](WidgetView, OptionList):
    """The native list owns the anchored rows and their theme paint."""

    width = height = AUTO
    position = "absolute"
    overlay = "screen"
    constrain_x = "inside"
    constrain_y = "inflect"
    vertical_scrollbar_size = horizontal_scrollbar_size = 0

    def __init__(self, anchor: Region, title: str, items) -> None:
        super().__init__(*(ContextMenuItem(action, label) for action, label in items))
        self.border_title = title
        # The menu opens just below what opened it, or just above when it does not fit:
        # it starts at the anchor with the anchor's height as its top margin, and an
        # inflected placement steps back over that margin.
        self.absolute_offset = anchor.offset
        self.margin = Spacing(anchor.height, 0, 0, 0)
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


class ContextMenu[Choice](HiddenActions, WidgetView, DismissibleScreen[Choice]):
    """Native dismissal owns Escape, selection, results and focus restoration."""

    width = height = FILL
    paint_background = TRANSPARENT

    def __init__(self, anchor: Region, title: str, items) -> None:
        """`anchor` is what opened the menu: a button's region, or a zero-size region at a pointer."""
        super().__init__()
        self.options = ContextMenuOptions[Choice](anchor, title, items)

    def compose(self):
        yield self.options

    @classmethod
    def show(cls, screen, anchor: Region, title: str, items, *, callback):
        menu = cls(anchor, title, items)
        screen.app.push_screen(menu, callback)
        return menu

    @classmethod
    async def choose(cls, screen, anchor: Region, title: str, items):
        return await screen.app.push_screen_wait(cls(anchor, title, items))

    @on(OptionList.OptionSelected)
    def item_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(cast(ContextMenuItem[Choice], event.option).action)

    @on(events.Click)
    def on_click(self, event: events.Click) -> None:
        if not self.options.region.contains(*event.screen_offset):
            event.stop()
            self.dismiss(None)


def show_target_menu(
    screen,
    anchor: Region,
    title: str,
    items: list[tuple[str, str]],
    actions: dict[str, Callable[[], None]],
) -> None:
    """Use the same modal menu for contextual declarations."""
    def handle(choice: str | None) -> None:
        if choice and choice in actions:
            actions[choice]()

    ContextMenu.show(screen, anchor, title, items, callback=handle)
