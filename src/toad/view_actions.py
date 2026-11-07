"""The workspace screen's keyboard actions, declared where every reader of them imports it.

Its own module because an action's words belong to the action: the jump button draws
`BackToBottomAction`'s title and key, and reaching them inside the workspace screen's
module would import the chrome that reaches the conversation, which holds the button.
A module both sides import is the repair for that cycle; a copy of the words in the
widget was the workaround.

Each action names the capability its context must have, as `widget_actions`' own actions
do (`DismissAction` takes a `DismissibleControl`), rather than the concrete screen class
it cannot import from here.
"""

from __future__ import annotations

from textual.document._editing import EditingMode
from textual.widget import Widget

from toad.app_node import ToadNode
from toad.history_jump import JumpsHistory
from toad.widget_actions import WidgetAction


class ViewAction(WidgetAction, affix="Action"):
    """What the workspace screen answers; `WorkspaceScreen` declares this family as its own."""


class ShowSidebarAction(ViewAction):
    title = 'Sidebar'
    keys = {EditingMode: ('ctrl+b', 'f20')}
    show = True

    def available(self, context: ToadNode) -> bool:
        sidebar = context.app.workspace_chrome.channels
        return sidebar.display and not sidebar.has_focus_within

    def apply(self, context: ToadNode) -> None:
        sidebar = context.app.workspace_chrome.channels
        sidebar.reveal()
        if title := sidebar.query_one_optional("SideBarCollapsible CollapsibleTitle"):
            title.focus()


class OpenBusAction(ViewAction):
    """Pick which bus this Toad opens, including a remote one it holds a profile for."""

    title = 'Open a bus'
    # Beside ctrl+b for the sidebar. Not a function key: f8 and f20 are claimed, and the
    # rest are what tests bind their own fixtures to, so an action taking one steals the
    # press a keymap test makes to prove nothing answers it.
    keys = {EditingMode: ('ctrl+shift+b',)}
    show = True

    def apply(self, context: ToadNode) -> None:
        from toad.screens.bus_choice import BusChoices

        context.app.push_screen(BusChoices.offered(), context.app.open_bus)


class BackToBottomAction(ViewAction):
    """Jump the shown history back to its latest message."""

    title = "Back to bottom"
    keys = {EditingMode: ("escape",)}
    key_display = "Esc"
    priority = True

    def available(self, context: JumpsHistory) -> bool:
        # The app's focused widget is the current screen's, and this screen is current
        # while its own key is being answered.
        match context.app.focused:
            case Widget(uses_screen_coordinates=True):
                return False
        return bool(context.back_to_bottom_windows)

    def apply(self, context: JumpsHistory) -> None:
        for window in context.back_to_bottom_windows[:1]:
            window.jump_to_latest()
