"""Availability and effects use the conversation's existing resource owners."""
from __future__ import annotations

from textual.widgets.text_area import EditingMode, VimMode
from textual.binding import Binding
from textual.geometry import Offset
from toad.widget_actions import Action, ExclusiveKeys
from toad.block_navigation import CursorDirection, DownCursor, UpCursor
from toad.menus import MenuItem
from toad.widgets.menu import Menu
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation, Window


class ConversationAction(Action, affix="Action"):
    pass


class BlockCursorAction(ConversationAction, declared_name=None):
    """Move between conversation blocks without moving the prompt's text cursor."""

    direction: type[CursorDirection]
    group = Binding.Group(description="Cursor")

    def apply(self, conversation: Conversation) -> None:
        conversation.move_cursor(self.direction())


class BlockCursorUpAction(BlockCursorAction):
    keys = {EditingMode: ("alt+up",)}
    direction = UpCursor
    priority = True


class BlockCursorDownAction(BlockCursorAction):
    keys = {EditingMode: ("alt+down",)}
    direction = DownCursor


class InterruptAction(ConversationAction):
    """Interrupt the running shell command."""

    keys = {EditingMode: ("ctrl+c",)}
    show = True

    def available(self, conversation: Conversation) -> bool:
        return conversation.can_interrupt_command

    async def apply(self, conversation: Conversation) -> None:
        await conversation.shell.interrupt()
        conversation.feedback.flash("Command interrupted", style="success")


class SelectBlockAction(ConversationAction):
    """Select this block and open its available operations."""

    keys = {EditingMode: ("enter",)}
    show = True

    async def apply(self, conversation: Conversation) -> None:
        cursor = conversation.navigation.cursor
        for block in cursor.selected_widgets:
            menu_options = [
                MenuItem("[u]C[/]opy to clipboard", "copy_to_clipboard", "c"),
                MenuItem("Co[u]p[/u]y to prompt", "copy_to_prompt", "p"),
                MenuItem("Open as S[u]V[/]G", "export_to_svg", "v"),
            ]
            if cursor.allow_maximize:
                menu_options.append(MenuItem("[u]M[/u]aximize", "maximize_block", "m"))
            menu_options.extend(cursor.get_block_menu())
            menu = Menu(block, menu_options, focus_owner=conversation.window)
            region = cursor.region
            menu.offset = Offset(1, region.y if region is not None else conversation.window.region.y)
            await conversation.mount(menu)
            menu.focus()


class WindowAction(Action, affix="Action"):
    """Reader-window actions retain their own native keyboard scope."""


class FocusPromptAction(WindowAction):
    """Go to the latest content and focus its prompt."""

    keys = {EditingMode: ("end",)}
    show = True

    def apply(self, window: Window) -> None:
        from toad.widgets.conversation import Conversation

        window.query_ancestor(Conversation).focus_prompt()


class FocusTerminalAction(ConversationAction):
    """Focus the active terminal."""

    keys = {EditingMode: ("ctrl+f",)}
    priority = True

    def available(self, conversation):
        return conversation.terminal_action_state

    async def apply(self, conversation):
        conversation.focus_terminal()


class ModeSwitcherAction(ConversationAction):
    """Open the mode switcher."""

    keys = {EditingMode: ("ctrl+o",)}
    show = True

    def available(self, conversation):
        return conversation.mode_selection_available

    async def apply(self, conversation):
        conversation.prompt.mode_switcher.focus()


class CancelAction(ConversationAction):
    """Cancel the agent's turn."""

    keys = {EditingMode: ("escape",), VimMode: ("alt+ctrl+x",)}
    show = True

    def available(self, conversation):
        return True if conversation.agent_binding.cancel_allowed(conversation.turns.owner) else None

    async def apply(self, conversation):
        conversation.cancel_turn(conversation.app.get_key_display(*self.active_bindings(conversation)))


class PageFractionAction(ConversationAction):
    """Scroll the conversation by a fraction of its visible height."""

    priority = True
    direction = -1
    page_divisor = 4

    async def apply(self, conversation):
        conversation.window.scroll_page_fraction(self.direction, self.page_divisor)


class QuarterPageUpAction(PageFractionAction):
    """Scroll the conversation up a quarter page."""

    keys = {EditingMode: ("pageup", "shift+pageup")}


class QuarterPageDownAction(QuarterPageUpAction):
    """Scroll the conversation down a quarter page."""

    keys = {EditingMode: ("pagedown", "shift+pagedown")}
    direction = 1


class EighthPageUpAction(PageFractionAction):
    """Scroll the conversation up an eighth of a page."""

    keys = {EditingMode: ("ctrl+pageup",)}
    page_divisor = 8


class EighthPageDownAction(EighthPageUpAction):
    """Scroll the conversation down an eighth of a page."""

    keys = {EditingMode: ("ctrl+pagedown",)}
    direction = 1


class BlockExpansionAction(ExclusiveKeys, ConversationAction, declared_name=None):
    """Expansion and collapse are alternatives selected by the cursor block's state."""
    keys = {EditingMode: ("space",)}
    key_display = "␣"
    show = True


class ExpandBlockAction(BlockExpansionAction):
    """Expand the block under the cursor."""

    def available(self, conversation):
        block = conversation.cursor_block
        return False if block is None else block.can_expand()

    async def apply(self, conversation):
        conversation.cursor_block.expand_block()
        conversation.refresh_bindings()
        conversation.call_after_refresh(conversation.cursor.refresh)


class CollapseBlockAction(BlockExpansionAction):
    """Collapse the block under the cursor."""

    def available(self, conversation):
        block = conversation.cursor_block
        return False if block is None else block.is_block_expanded()

    async def apply(self, conversation):
        conversation.cursor_block.collapse_block()
        conversation.refresh_bindings()
        conversation.call_after_refresh(conversation.cursor.refresh)
