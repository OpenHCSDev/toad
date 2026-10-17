from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import ListView, Label
from textual import events
from textual.widget import Widget
from textual.layouts.horizontal import HorizontalLayout

from toad.menus import MenuItem
from toad.widgets.selection import SelectionListItem



class NonSelectableLabel(Label):
    ALLOW_SELECT = False


class MenuOption(SelectionListItem):
    ALLOW_SELECT = False
    DEFAULT_LAYOUT = HorizontalLayout

    def __init__(self, action: str | None, description: str, key: str | None) -> None:
        self._action = action
        self._description = description
        self._key = key
        super().__init__(classes="-has-key" if key else "-no_key")

    def compose(self) -> ComposeResult:
        yield NonSelectableLabel(self._key or " ", id="key")
        yield NonSelectableLabel(self._description, id="description")


class Menu(ListView, can_focus=True):
    BINDINGS = [Binding("escape", "dismiss", "Dismiss")]

    DEFAULT_CSS = """
    Menu {
        margin: 1 1;
        width: auto;
        height: auto;        
        max-width: 100%;
        overlay: screen;  
        position: absolute;
        color: $foreground;
        background: $panel;
        border: block $panel;
        constrain: inside inside;
   
        & > MenuOption {         
            
            width: 1fr;            
            padding: 0 1;
            height: auto !important;
            overflow: auto;
            expand: optimal;            
            #description {                        
                width: 1fr;                    
            }
            #key {                
                padding-right: 1;                
                text-style: bold;
            }                            
           
        }

        &:blur {
            background-tint: transparent;
            & > ListItem.-highlight {
                color: $block-cursor-blurred-foreground;
                background: $block-cursor-blurred-background;
                text-style: $block-cursor-blurred-text-style;
            }
        }
        
        &:focus {
            background-tint: transparent;
            & > ListItem.-highlight {
                color: $block-cursor-foreground;
                background: $block-cursor-background;
                text-style: $block-cursor-text-style;
            }
        }
    }
    """

    @dataclass
    class OptionSelected(Message):
        """The user selected on of the options."""

        menu: Menu
        owner: Widget
        action: str | None

    @dataclass
    class Dismissed(Message):
        """Menu was dismissed."""

        menu: Menu

    def __init__(self, owner: Widget, options: list[MenuItem], *args, focus_owner: Widget, **kwargs) -> None:
        self._owner = owner
        self._focus_owner = focus_owner
        self._options = sorted(options, key=lambda option: option.key is None)
        super().__init__(*args, **kwargs)

    def _insert_options(self) -> None:
        self.extend(
            MenuOption(menu_item.action, menu_item.description, menu_item.key)
            for menu_item in self._options
        )

    def on_mount(self) -> None:
        self._insert_options()

    async def activate_index(self, index: int) -> None:
        action = self._options[index].action
        self.post_message(self.OptionSelected(self, self._owner, action))
        self.action_dismiss()

    def action_dismiss(self) -> None:
        if self.is_leaving:
            return
        self.post_message(self.Dismissed(self))
        if self.has_focus:
            self.screen.set_focus(self._focus_owner, scroll_visible=False)
        self.display = False
        self.remove()

    def on_blur(self) -> None:
        self.action_dismiss()

    @on(events.Key)
    async def on_key(self, event: events.Key) -> None:
        for index, option in enumerate(self._options):
            if event.key == option.key:
                self.index = index
                event.stop()
                await self.activate_index(index)
                break

    @on(ListView.Selected)
    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        await self.activate_index(event.index)
