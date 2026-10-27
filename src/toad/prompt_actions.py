"""Prompt bindings, eligibility and effects share the native action owners."""
from __future__ import annotations
from textual.widgets.text_area import EditingMode
from toad.widget_actions import Action, ExclusiveBackground
from pathlib import Path
from typing import TYPE_CHECKING, Literal, ClassVar
import asyncio
import shlex
from toad.clipboard_image import read_clipboard_png, save_clipboard_png


if TYPE_CHECKING:
    from toad.widgets.prompt import PromptTextArea


class PromptAction(Action["PromptTextArea"], affix="Action"):
    pass


class EnterShellAction(PromptAction):
    """Run the prompt as a shell command."""

    keys = {EditingMode: ("exclamation_mark",)}
    priority = True

    def available(self, editor):
        return editor.can_enter_shell

    async def apply(self, editor: PromptTextArea) -> None:
        editor.prompt.shell_mode = True


class SubmitAction(PromptAction):
    """Send the prompt to the agent."""

    keys = {EditingMode: ("enter",)}
    title = "Send"
    key_display: ClassVar[str | None] = "⏎"
    priority = True

    def available(self, editor):
        return editor.submission_allowed

    async def apply(self, editor: PromptTextArea) -> None:
        editor.schedule_submission()


class SubmitNowAction(SubmitAction):
    """Send the prompt now, ahead of the queue."""

    keys = {EditingMode: ("ctrl+enter", "ctrl+y")}
    title = "Send now"
    key_display = None

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


class PasteClipboardAction(ExclusiveBackground["PromptTextArea"], PromptAction):
    """Paste clipboard text or attach a clipboard PNG without blocking keyboard input."""
    keys = {EditingMode: ("ctrl+v",)}
    priority = True

    async def perform(self, editor: PromptTextArea) -> None:
        if editor.read_only:
            return
        try:
            image = await read_clipboard_png()
            if not editor.is_attached:
                return
            if image is not None:
                if editor.shell_mode:
                    editor.notify(
                        "Leave shell mode to attach an image to a message.",
                        title="Image attachment",
                        severity="warning",
                    )
                    return
                path = await asyncio.to_thread(save_clipboard_png, image)
                reference = (
                    f'@"{path}"'
                    if any(char.isspace() for char in str(path))
                    else f"@{path}"
                )
                editor._paste_clipboard_text(" " + reference + " ")
                editor.notify(
                    f"PNG attached ({len(image):,} bytes). Enter sends it with your prompt.",
                    title="Image attachment",
                )
                return
            text = (await editor.app.clipboard_transport.paste(editor.app)).text
            if text:
                editor._paste_clipboard_text(text)
            else:
                editor.notify(
                    "No text or supported image in the clipboard", title="Paste"
                )
        except (OSError, ValueError, TimeoutError) as error:
            editor.app.show_error(error, "Paste failed")


class CompleteShellPathAction(PromptAction):
    """Complete the shell path or cycle the matching file suggestions."""
    keys = {EditingMode: ("tab",)}
    priority = True

    async def apply(self, editor: PromptTextArea) -> None:
        if not editor.editing_mode.accepts_text or not editor.shell_mode:
            return

        prompt = editor.prompt

        if not editor.cursor_at_end_of_text:
            return

        _cursor_row, cursor_column = prompt.prompt_text_area.selection.end
        pre_complete = editor.text[:cursor_column]
        post_complete = editor.text[cursor_column:]
        shlex_tokens = shlex.split(pre_complete)
        if not shlex_tokens:
            return

        command = shlex_tokens[0]

        exclude_node_type: Literal["file"] | Literal["dir"] | None = None
        if command in editor.app.settings.shell.directory_commands.splitlines():
            exclude_node_type = "file"
        elif command in editor.app.settings.shell.file_commands.splitlines():
            exclude_node_type = "dir"

        tab_complete, suggestions = await editor.path_complete(
            Path(prompt.working_directory),
            shlex_tokens[-1],
            exclude_type=exclude_node_type,
        )

        if tab_complete is not None:
            shlex_tokens = shlex_tokens[:-1] + [shlex_tokens[-1] + tab_complete]
            path_component = Path(prompt.working_directory) / shlex_tokens[-1]
            if path_component.is_file():
                spaces = " "
            else:
                spaces = ""

            editor.clear()
            editor.insert(
                " ".join(token.replace(" ", "\\ ") for token in shlex_tokens)
                + post_complete
                + spaces
            )
            editor.suggestions = None
        else:
            if suggestions != editor.suggestions:
                editor.suggestions = suggestions or None
                editor.suggestions_index = 0
                if suggestions:
                    editor.suggestion = suggestions[0]
            elif editor.suggestions:
                editor.suggestions_index = (editor.suggestions_index + 1) % len(
                    editor.suggestions
                )
                editor.suggestion = editor.suggestions[editor.suggestions_index]
