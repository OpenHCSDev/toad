"""Availability and effects use the conversation's existing resource owners."""
from __future__ import annotations

from agent_comms.declared_family import DeclaredFamily
from toad.application_actions import NativeAction, KeyboundAction
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation


class ConversationAction(NativeAction["Conversation"], DeclaredFamily, affix="Action"):
    pass


class FocusTerminalAction(KeyboundAction, ConversationAction):
    key = "ctrl+f"
    description = "Focus"
    tooltip = "Focus the active terminal"
    priority = True

    def available(self, conversation):
        return None if conversation._terminal is None else True

    async def apply(self, conversation):
        conversation._terminal.focus()


class ModeSwitcherAction(KeyboundAction, ConversationAction):
    key = "ctrl+o"
    description = "Modes"
    tooltip = "Open the mode switcher"
    show = True

    def available(self, conversation):
        return bool(conversation.modes)

    async def apply(self, conversation):
        conversation.prompt.mode_switcher.focus()


class CancelAction(KeyboundAction, ConversationAction):
    key = "escape"
    description = "Cancel"
    tooltip = "Cancel agent's turn"
    show = True

    def available(self, conversation):
        return True if conversation.agent and conversation.turns.owner.busy else None

    async def apply(self, conversation):
        conversation.cancel_turn()


class ExpandBlockAction(KeyboundAction, ConversationAction):
    key = "space"
    description = "Expand"
    tooltip = "Expand cursor block"
    key_display = "␣"
    show = True

    def available(self, conversation):
        block = conversation.cursor_block
        return False if block is None else block.can_expand()

    async def apply(self, conversation):
        conversation.cursor_block.expand_block()
        conversation.refresh_bindings()
        conversation.call_after_refresh(conversation.cursor.refresh)


class CollapseBlockAction(KeyboundAction, ConversationAction):
    key = "space"
    description = "Collapse"
    tooltip = "Collapse cursor block"
    key_display = "␣"
    show = True

    def available(self, conversation):
        block = conversation.cursor_block
        return False if block is None else block.is_block_expanded()

    async def apply(self, conversation):
        conversation.cursor_block.collapse_block()
        conversation.refresh_bindings()
        conversation.call_after_refresh(conversation.cursor.refresh)
