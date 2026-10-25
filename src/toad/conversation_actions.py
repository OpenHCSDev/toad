"""Availability and effects use the conversation's existing resource owners."""
from __future__ import annotations

from toad.widget_actions import Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation


class ConversationAction(Action, affix="Action"):
    pass


class FocusTerminalAction(ConversationAction):
    """Focus the active terminal."""

    keys = ("ctrl+f",)
    priority = True

    def available(self, conversation):
        return conversation.terminal_action_state

    async def apply(self, conversation):
        conversation.focus_terminal()


class ModeSwitcherAction(ConversationAction):
    """Open the mode switcher."""

    keys = ("ctrl+o",)
    show = True

    def available(self, conversation):
        return conversation.mode_selection_available

    async def apply(self, conversation):
        conversation.prompt.mode_switcher.focus()


class CancelAction(ConversationAction):
    """Cancel the agent's turn."""

    keys = ("escape",)
    show = True
    vim_profile = False

    def available(self, conversation):
        if conversation.app.settings.ui.vim_keys != self.vim_profile:
            return False
        return True if conversation.agent_binding.cancel_allowed(conversation.turns.owner) else None

    async def apply(self, conversation):
        conversation.cancel_turn(conversation.app.get_key_display(*self.bindings()))


class VimCancelAction(CancelAction):
    keys = ("alt+ctrl+x",)
    key_display = "Ctrl+Alt+X"
    vim_profile = True


class QuarterPageUpAction(ConversationAction):
    """Scroll the conversation up a quarter page."""

    keys = ("shift+pageup",)
    direction = -1

    async def apply(self, conversation):
        conversation.window.scroll_quarter_page(self.direction)


class QuarterPageDownAction(QuarterPageUpAction):
    """Scroll the conversation down a quarter page."""

    keys = ("shift+pagedown",)
    direction = 1


class ExpandBlockAction(ConversationAction):
    """Expand the block under the cursor."""

    keys = ("space",)
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

    keys = ("space",)
    key_display = "␣"
    show = True

    def available(self, conversation):
        block = conversation.cursor_block
        return False if block is None else block.is_block_expanded()

    async def apply(self, conversation):
        conversation.cursor_block.collapse_block()
        conversation.refresh_bindings()
        conversation.call_after_refresh(conversation.cursor.refresh)
