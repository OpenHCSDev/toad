"""Prompt bindings, eligibility and effects share the native action owners."""
from agent_comms.declared_family import DeclaredFamily
from toad.application_actions import KeyboundAction, NativeAction


class PromptAction(NativeAction, DeclaredFamily, affix="Action"):
    pass


class SubmitAction(KeyboundAction, PromptAction):
    key = "enter"
    description = "Send"
    key_display = "⏎"
    tooltip = "Send the prompt to the agent"
    priority = True

    async def apply(self, editor):
        editor.schedule_submission()


class SubmitNowAction(KeyboundAction, PromptAction):
    key = "ctrl+enter,ctrl+y"
    description = "Send now"
    priority = True

    def available(self, editor):
        return editor.agent_ready and editor.agent_busy and editor.queue_supported

    async def apply(self, editor):
        editor.schedule_submission(immediate=True)


class ClearInputAction(KeyboundAction, PromptAction):
    key = "ctrl+c"
    description = "Clear"
    tooltip = "Clear the prompt"
    priority = True
    show = False

    def available(self, editor):
        return bool(editor.text)

    async def apply(self, editor):
        editor.clear()
        editor.suggestions = None
        editor.suggestion = ""
