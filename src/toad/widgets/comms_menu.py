"""One retained, pointer-anchored menu widget per native screen."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast

from textual import events, on
from textual.binding import Binding
from textual.css._style_properties import Edges
from textual.geometry import Offset
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from ui_theme.scheme import BackgroundColour, ForegroundColour, PrimaryColour
from toad.widget_view import AUTO, WidgetView


class ContextMenuItem[Choice](Option):
    def __init__(self, action: Choice, label: str) -> None:
        super().__init__(label)
        self.action = action


class ContextMenu[Choice](WidgetView, OptionList):
    """Native OptionList owns rows and input; opening only changes its view."""

    width = height = AUTO
    position = "absolute"
    overlay = "screen"
    layer_name = "_tooltips"
    constrain_x = constrain_y = "inside"
    vertical_scrollbar_size = horizontal_scrollbar_size = 0
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self) -> None:
        super().__init__()
        self.visible = False
        self._callback = None
        self._return_focus = None

    @property
    def border(self):
        return Edges(*(("solid", self.app.colours.colour(PrimaryColour)),) * 4)

    @property
    def paint_background(self):
        return self.app.colours.colour(BackgroundColour)

    @property
    def paint_foreground(self):
        return self.app.colours.colour(ForegroundColour)

    @classmethod
    def show(cls, screen, menu_offset: Offset, title: str, items, *, callback):
        menu = screen.query_one_optional(cls)
        if menu is None:
            menu = cls()
            screen.mount(menu)
        menu.close(None)
        items = tuple(items)
        if menu.option_count != len(items):
            menu.clear_options()
            menu.add_options(ContextMenuItem(action, label) for action, label in items)
        else:
            for index, (action, label) in enumerate(items):
                option = cast(ContextMenuItem, menu.get_option_at_index(index))
                option.action = action
                if option.prompt != label:
                    menu.replace_option_prompt_at_index(index, label)
        menu.border_title = title
        menu._callback = callback
        menu._return_focus = screen.focused
        if menu.absolute_offset != menu_offset:
            menu.absolute_offset = menu_offset
            menu.refresh(layout=True)
        menu.highlighted = 0 if items else None
        menu.visible = True
        menu.focus(scroll_visible=False)
        menu.capture_mouse()
        return menu

    @classmethod
    async def choose(cls, screen, menu_offset: Offset, title: str, items):
        result = asyncio.get_running_loop().create_future()

        def selected(choice):
            if not result.done():
                result.set_result(choice)

        menu = cls.show(screen, menu_offset, title, items, callback=selected)
        try:
            return await result
        finally:
            if menu._callback is selected:
                menu.close(None)

    def close(self, choice) -> None:
        callback, self._callback = self._callback, None
        previous, self._return_focus = self._return_focus, None
        self.visible = False
        self.release_mouse()
        if previous is not None and previous.is_attached and previous.screen.is_active:
            previous.focus(scroll_visible=False)
        if callback is not None:
            self.app.call_next(callback, choice)

    def action_cancel(self) -> None:
        self.close(None)

    @on(OptionList.OptionSelected)
    def item_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.close(cast(ContextMenuItem[Choice], event.option).action)

    def on_click(self, event: events.Click) -> None:
        if not self.region.contains(*event.screen_offset):
            event.stop()
            self.close(None)

    def on_blur(self) -> None:
        self.close(None)

    def on_unmount(self) -> None:
        self.close(None)


def show_target_menu(
    screen,
    menu_offset: Offset,
    title: str,
    items: list[tuple[str, str]],
    actions: dict[str, Callable[[], None]],
) -> None:
    """Use the same screen-owned overlay for contextual declarations."""
    def handle(choice: str | None) -> None:
        if choice and choice in actions:
            actions[choice]()

    ContextMenu.show(screen, menu_offset, title, items, callback=handle)
