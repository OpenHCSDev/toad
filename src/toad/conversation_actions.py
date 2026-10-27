"""Availability and effects use the conversation's existing resource owners."""
from __future__ import annotations

from textual.widgets.text_area import EditingMode, VimMode
from toad.widget_actions import Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation


class ConversationAction(Action, affix="Action"):
    pass


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


class ExpandBlockAction(ConversationAction):
    """Expand the block under the cursor."""

    keys = {EditingMode: ("space",)}
    key_display = "␣"
    show = True

    def available(self, conversation):
        block = conversation.cursor_block
        return False if block is None else block.can_expand()

    async def apply(self, conversation):
        conversation.cursor_block.expand_block()
        conversation.refresh_bindings()
        conversation.call_after_refresh(conversation.cursor.refresh)


class CollapseBlockAction(ConversationAction):
    """Collapse the block under the cursor."""

    keys = {EditingMode: ("space",)}
    key_display = "␣"
    show = True

    def available(self, conversation):
        block = conversation.cursor_block
        return False if block is None else block.is_block_expanded()

    async def apply(self, conversation):
        conversation.cursor_block.collapse_block()
        conversation.refresh_bindings()
        conversation.call_after_refresh(conversation.cursor.refresh)
