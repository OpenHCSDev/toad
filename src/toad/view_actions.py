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

from abc import abstractmethod


from formbridge.key_declarations import TextEntryMode

from toad.app_node import ToadNode
from toad.history_jump import JumpsHistory
from toad.widget_actions import WidgetAction


class ViewAction(WidgetAction, affix="Action"):
    """What the workspace screen answers; `WorkspaceScreen` declares this family as its own."""


class ShowSidebarAction(ViewAction):
    title = 'Sidebar'
    keys = {TextEntryMode: ('ctrl+b', 'f20')}
    show = True
    # It reveals Textual's workspace chrome by querying Textual's DOM.
    context_capability = ToadNode

    def available(self, context: ToadNode) -> bool:
        sidebar = context.app.workspace_chrome.channels
        return sidebar.display and not sidebar.has_focus_within

    def apply(self, context: ToadNode) -> None:
        sidebar = context.app.workspace_chrome.channels
        sidebar.reveal()
        if title := sidebar.query_one_optional("SideBarCollapsible CollapsibleTitle"):
            title.focus()


class BackToBottomAction(ViewAction):
    """Jump the shown history back to its latest message."""

    title = "Back to bottom"
    keys = {TextEntryMode: ("escape",)}
    key_display = "Esc"
    priority = True
    context_capability = JumpsHistory

    def available(self, context: JumpsHistory) -> bool:
        return context.takes_jump_key() and bool(context.back_to_bottom_windows)

    def apply(self, context: JumpsHistory) -> None:
        for window in context.back_to_bottom_windows[:1]:
            window.jump_to_latest()


class LatestJumpBar:
    """The control a history window floats over its foot while the reader is off the tail.

    Its words are `BackToBottomAction`'s own declaration: what the action does, then the key
    that does it. The window decides when it shows (`JumpsToLatest.tail_follow_changed`);
    each toolkit's bar only paints that. A plain mixin, as `JumpsToLatest` is: Textual's
    widget metaclass refuses an `ABC` base and Qt's shiboken metaclass clashes with one.
    """

    label = f"{BackToBottomAction.title}\n↓ {BackToBottomAction.key_display} ↓"

    @property
    @abstractmethod
    def jump_shown(self) -> bool:
        """Whether the bar is drawn now."""

    @abstractmethod
    def show_jump(self, shown: bool) -> None:
        """Draw the bar, or stop drawing it."""
