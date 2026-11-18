"""Prompt bindings, eligibility and effects share the native action owners."""
from __future__ import annotations
from formbridge.key_declarations import TextEntryMode
from textual.document._editing import VimMode

from toad.widget_actions import Action, EngineKey
from toad.core.input_events import UserInputSubmitted
from agent_comms.messaging.message_files import FileUpload
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from toad.widgets.prompt import PromptTextArea


class PromptAction(Action, affix="Action"):
    pass


class StandardEditingAction(PromptAction):
    """Escape from Neovim's idle Normal mode leaves the box for Standard navigation.

    Neovim receives the key first and offers it back from the mode the keys before it
    produced. A decision taken here from the last completed snapshot would treat a
    second Escape typed before Neovim answered the first as one more Escape in Insert.
    """

    keys = {VimMode: ("escape",)}
    declared_key = EngineKey()

    def available(self, editor):
        return editor.editing_mode.allows_application_commands

    async def apply(self, editor: PromptTextArea) -> None:
        editor.leave_modal_editor()

    def engine_boundary(self, editor: PromptTextArea) -> bool:
        if not editor.editing_mode.boundary_state.allows_application_commands:
            return False
        editor.leave_modal_editor()
        return True


class EnterShellAction(PromptAction):
    """Run the prompt as a shell command."""

    keys = {TextEntryMode: ("exclamation_mark",)}
    priority = True

    def available(self, editor):
        return editor.can_enter_shell

    async def apply(self, editor: PromptTextArea) -> None:
        editor.prompt.shell_mode = True


class AttachFileAction(PromptAction):
    """Attach a file to the message: the picker the file picker setting names opens."""

    keys = {TextEntryMode: ("ctrl+t",)}
    title = "Attach"

    async def apply(self, editor: PromptTextArea) -> None:
        editor.prompt.attach_file()


class SubmitInputAction(PromptAction, declared_name=None):
    """Submission shares eligibility, while each command owns how it sends."""
    priority = True

    def available(self, editor):
        return editor.submission_allowed

    async def apply(self, editor: PromptTextArea) -> None:
        editor.schedule_submission(self)

    def coalesce(self, following: SubmitInputAction) -> SubmitInputAction:
        return following

    def submission_event(self, text: str, shell: bool, files: tuple[FileUpload, ...]) -> UserInputSubmitted:
        return UserInputSubmitted(text, shell, files=files)


class SubmitAction(SubmitInputAction):
    """Send the prompt to the agent."""
    saved_key = "PromptSubmitAction"  # toad.widget_actions.SubmitAction is saved as SubmitAction
    keys = {TextEntryMode: ("enter",)}
    title = "Send"
    key_display = "⏎"


class SubmitNowAction(SubmitInputAction):
    """Send the prompt now, ahead of the queue."""

    keys = {TextEntryMode: ("ctrl+enter", "ctrl+y")}
    title = "Send now"

    def available(self, editor):
        return super().available(editor) and editor.prompt.agent_ready and editor.prompt.holds_input

    def coalesce(self, following: SubmitInputAction) -> SubmitInputAction:
        return self

    def submission_event(self, text: str, shell: bool, files: tuple[FileUpload, ...]) -> UserInputSubmitted:
        return UserInputSubmitted(text, shell, immediate=True, files=files)


class CopyOrClearInputAction(PromptAction):
    """Copy selected text or clear the prompt."""

    keys = {TextEntryMode: ("ctrl+c",)}
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


class CompleteAction(PromptAction):
    """Complete what precedes the cursor: a shell path in a shell prompt, a member in a channel."""

    keys = {TextEntryMode: ("tab",)}
    priority = True

    async def apply(self, editor: PromptTextArea) -> None:
        await editor.tab_complete()


class PasteClipboardAction(PromptAction):
    """Paste clipboard text, or attach a clipboard PNG image."""

    keys = {TextEntryMode: ("ctrl+v",)}
    priority = True

    def apply(self, editor: PromptTextArea) -> None:
        editor.paste_clipboard()


class NewlineAction(PromptAction):
    """Insert a new line in the prompt."""
    title = "New line"
    keys = {TextEntryMode: ("ctrl+j", "shift+enter")}
    priority = True
    show = True

    async def apply(self, editor: PromptTextArea) -> None:
        editor._replace_via_keyboard("\n", *editor.selection)
