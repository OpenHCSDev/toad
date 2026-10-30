from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from textual.binding import BindingsMap, KeymapClaim
from textual.document._editing import EditingMode

from textual import on
from textual.app import ComposeResult
from toad.widget_actions import DismissibleControl
from textual.message import Message
from textual.widgets import ListView, Label
from textual.widget import Widget
from textual.layouts.horizontal import HorizontalLayout

from toad.app_node import ToadNode
from toad.menus import MenuCommand, MenuConversation, MenuOwner
from toad.keymap import KeymapCatalog
from toad.widgets.selection import SelectionListItem
from toad.tone_paint import UntintedTonePaint


class NonSelectableLabel(Label):
    ALLOW_SELECT = False


class MenuOption(SelectionListItem, ToadNode):
    ALLOW_SELECT = False
    DEFAULT_LAYOUT = HorizontalLayout

    def __init__(self, command: MenuCommand) -> None:
        self.command = command
        super().__init__()

    def compose(self) -> ComposeResult:
        yield NonSelectableLabel(" ", id="key")
        yield NonSelectableLabel(self.command.description, id="description")

    def refresh_key(self) -> None:
        keys = KeymapCatalog.menu_keys(self.command, self.app.settings.ui.key_mode,
                                      self.app.settings.ui.keymap)
        self.query_one("#key", NonSelectableLabel).update(", ".join(keys) or " ")
        self.set_class(bool(keys), "-has-key")
        self.set_class(not keys, "-no_key")


class Menu(DismissibleControl, UntintedTonePaint, ListView, MenuOwner, can_focus=True):

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

    }
    """

    @dataclass
    class OptionSelected(Message):
        """The user selected on of the options."""

        menu: Menu
        command: MenuCommand

    def __init__(self, conversation: MenuConversation, owner: Widget,
                 commands: Sequence[MenuCommand], *args, focus_owner: Widget, **kwargs) -> None:
        self.conversation = conversation
        self.block = owner
        self._focus_owner = focus_owner
        self._commands = tuple(sorted(commands, key=lambda command: not type(command).default_keys()))
        super().__init__(*args, **kwargs)

    @classmethod
    def keymap_claims(cls, mode: type[EditingMode]) -> tuple[KeymapClaim, ...]:
        return (
            *super().keymap_claims(mode),
            *(KeymapClaim(declaration, declaration.default_keys())
              for declaration in MenuCommand.members_with(MenuCommand)),
        )

    def binding_map(self, mode: type[EditingMode]) -> BindingsMap:
        return BindingsMap.merge((super().binding_map(mode), BindingsMap(
            binding for command in self._commands for binding in command.bindings(mode))))

    def _insert_options(self) -> None:
        self.extend(
            MenuOption(command) for command in self._commands
        )

    def on_mount(self) -> None:
        self._insert_options()
        self.screen.bindings_updated_signal.subscribe(self, self.refresh_keys)
        self.call_after_refresh(self.refresh_keys)

    def on_unmount(self) -> None:
        self.screen.bindings_updated_signal.unsubscribe(self)

    def refresh_keys(self, _screen: object = None) -> None:
        for option in self.query(MenuOption):
            option.refresh_key()

    async def activate_index(self, index: int) -> None:
        self.activate_command(self._commands[index])

    def activate_command(self, command: MenuCommand) -> None:
        self.post_message(self.OptionSelected(self, command))
        self.dismiss_control()

    def dismiss_control(self) -> None:
        if self.is_leaving:
            return
        if self.has_focus:
            self.screen.set_focus(self._focus_owner, scroll_visible=False)
        self.display = False
        self.remove()

    def on_blur(self) -> None:
        self.dismiss_control()

    @on(ListView.Selected)
    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        await self.activate_index(event.index)
