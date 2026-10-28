"""Prompt bindings, eligibility and effects share the native action owners."""
from __future__ import annotations
from textual.widgets.text_area import EditingMode
from toad.widget_actions import Action
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from toad.widgets.prompt import PromptTextArea


class PromptAction(Action, affix="Action"):
    pass


class EnterShellAction(PromptAction):
    """Run the prompt as a shell command."""

    keys = {EditingMode: ("exclamation_mark",)}
    priority = True

    def available(self, editor):
        return editor.can_enter_shell

    async def apply(self, editor: PromptTextArea) -> None:
        editor.prompt.shell_mode = True


class SubmitInputAction(PromptAction, declared_name=None):
    """Submission shares eligibility, while each command owns how it sends."""
    priority = True

    def available(self, editor):
        return editor.submission_allowed


class SubmitAction(SubmitInputAction):
    """Send the prompt to the agent."""
    keys = {EditingMode: ("enter",)}
    title = "Send"
    key_display = "⏎"

    async def apply(self, editor: PromptTextArea) -> None:
        editor.schedule_submission()


class SubmitNowAction(SubmitInputAction):
    """Send the prompt now, ahead of the queue."""

    keys = {EditingMode: ("ctrl+enter", "ctrl+y")}
    title = "Send now"

    def available(self, editor):
        return (super().available(editor) and editor.agent_ready and editor.agent_busy
                and editor.prompt.agent_binding.presentation.queue_supported)

    async def apply(self, editor: PromptTextArea) -> None:
        editor.schedule_submission(immediate=True)


class CopyOrClearInputAction(PromptAction):
    """Copy selected text or clear the prompt."""

    keys = {EditingMode: ("ctrl+c",)}
    priority = True

    def available(self, editor):
        return bool(editor.text)

    async def apply(self, editor: PromptTextArea) -> None:
        if editor.selected_text:
            editor.action_copy()
            return
        editor.editing_mode.suspend(editor)
        editor.clear()
        editor.editing_mode.resume(editor)
        editor.clear_suggestions()


class NewlineAction(PromptAction):
    """Insert a new line in the prompt."""
    title = "New line"
    keys = {EditingMode: ("ctrl+j", "shift+enter")}
    priority = True
    show = True

    async def apply(self, editor: PromptTextArea) -> None:
        editor._replace_via_keyboard("\n", *editor.selection)
