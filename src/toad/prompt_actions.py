"""Prompt bindings, eligibility and effects share the native action owners."""
from toad.widget_actions import Action


class PromptAction(Action, affix="Action"):
    pass


class EnterShellAction(PromptAction):
    """Run the prompt as a shell command."""

    keys = ("exclamation_mark",)
    priority = True

    def available(self, editor):
        return editor.can_enter_shell

    async def apply(self, editor):
        editor.prompt.shell_mode = True


class SubmitAction(PromptAction):
    """Send the prompt to the agent."""

    keys = ("enter",)
    title = "Send"
    key_display = "⏎"
    priority = True

    def available(self, editor):
        return editor.submission_allowed

    async def apply(self, editor):
        editor.schedule_submission()


class SubmitNowAction(SubmitAction):
    """Send the prompt now, ahead of the queue."""

    keys = ("ctrl+enter", "ctrl+y")
    title = "Send now"
    key_display = None

    def available(self, editor):
        return (super().available(editor) and editor.agent_ready and editor.agent_busy
                and editor.prompt.agent_binding.presentation.queue_supported)

    async def apply(self, editor):
        editor.schedule_submission(immediate=True)


class CopyOrClearInputAction(PromptAction):
    """Copy selected text or clear the prompt."""

    keys = ("ctrl+c",)
    priority = True

    def available(self, editor):
        return bool(editor.text)

    async def apply(self, editor):
        if editor.selected_text:
            editor.action_copy()
            return
        editor.editing_mode.suspend(editor)
        editor.clear()
        editor.editing_mode.resume(editor)
        editor.suggestions = None
        editor.suggestion = ""
