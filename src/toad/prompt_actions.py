"""Prompt bindings, eligibility and effects share the native action owners."""
from agent_comms.declared_family import DeclaredFamily
from toad.widget_actions import KeyboundAction, NativeAction


class PromptAction(NativeAction, DeclaredFamily, affix="Action"):
    pass


class EnterShellAction(KeyboundAction, PromptAction):
    key = "exclamation_mark"
    description = "Shell command"
    priority = True

    def available(self, editor):
        return editor.can_enter_shell

    async def apply(self, editor):
        from toad.widgets.prompt import Prompt

        editor.query_ancestor(Prompt).shell_mode = True


class SubmitAction(KeyboundAction, PromptAction):
    key = "enter"
    description = "Send"
    key_display = "⏎"
    tooltip = "Send the prompt to the agent"
    priority = True

    def available(self, editor):
        return editor.submission_allowed

    async def apply(self, editor):
        editor.schedule_submission()


class SubmitNowAction(SubmitAction):
    key = "ctrl+enter,ctrl+y"
    key_display = None
    description = "Send now"
    priority = True

    def available(self, editor):
        return super().available(editor) and editor.agent_ready and editor.agent_busy and editor.queue_supported

    async def apply(self, editor):
        editor.schedule_submission(immediate=True)


class CopyOrClearInputAction(KeyboundAction, PromptAction):
    key = "ctrl+c"
    description = "Copy / Clear"
    tooltip = "Copy selected text or clear the prompt"
    priority = True
    show = False

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
