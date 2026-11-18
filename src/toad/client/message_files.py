"""The files a message composer attaches, from the picker to the send. No toolkit here.

The attach action opens the picker the `ui.input.file_picker` setting names. Each frontend
answers only its pickers and how it draws the attached files: Qt's composer opens a file
dialog (on Android, the system's own file picker) or its path search, and Textual's prompt
opens its terminal pickers. A picked file becomes the upload Core checks again. The files
ride the submission with the text, and a send that does not land returns them to the
composer with its draft.
"""

from __future__ import annotations

import mimetypes
from abc import abstractmethod

from agent_comms.messaging.message_files import FileUpload
from agent_comms.nominal.declared_choice import DeclaredChoice, TitledChoice

from toad.client.input_decision import InputAccepted, InputDecision
from toad.client.prompt_composer import PromptComposer


class FilePicker(DeclaredChoice, affix="FilePicker"):
    """Which picker the attach action opens; each member names the composer's own."""

    @classmethod
    @abstractmethod
    def open(cls, composer: MessagePromptComposer) -> None: ...


class WindowFilePicker(TitledChoice, FilePicker):
    """The platform's file dialog. A phone shows its own file picker, which reaches the
    phone's storage and its cloud drives."""

    title = "File dialog"

    @classmethod
    def open(cls, composer: MessagePromptComposer) -> None:
        composer.pick_in_window()


class PathSearchFilePicker(TitledChoice, FilePicker):
    """The path search @ completion uses, over the project's files."""

    title = "Project path search"

    @classmethod
    def open(cls, composer: MessagePromptComposer) -> None:
        composer.pick_by_path_search()


def file_size(size: int) -> str:
    """A size as a reader takes it in at a glance."""
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


class MessagePromptComposer(PromptComposer):
    """A message composer: always the agent glyph, every input accepted, and the files it
    sends with the text."""

    attached_files: tuple[FileUpload, ...] = ()

    @property
    def input_decision(self) -> InputDecision:
        """A message is accepted whether or not an agent is attached: its submission owner
        refuses a send it cannot make. An agent prompt asks its owner instead."""
        return InputAccepted()

    def prompt_symbol(self, text: str, shell_mode: bool) -> str:
        return self.settings.ui.input.agent_symbol

    def attach_file(self) -> None:
        """The attach action: the picker this composer's settings name opens."""
        self.settings.ui.input.file_picker.open(self)

    @abstractmethod
    def pick_in_window(self) -> None:
        """Open this frontend's file dialog; what it returns reaches `file_picked`."""

    @abstractmethod
    def pick_by_path_search(self) -> None:
        """Open this frontend's path search; what it returns reaches `file_picked`."""

    @abstractmethod
    def show_attached(self) -> None:
        """Draw `attached_files` beside the editor, each with a way to take it off."""

    @abstractmethod
    def show_failure(self, text: str) -> None:
        """Tell the person why nothing was attached."""

    def file_picked(self, name: str, content: bytes, mime_type: str = "") -> None:
        """A picker returned a file: attach it, or say why it cannot go with this message."""
        try:
            upload = FileUpload.of(
                name, mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream", content)
            FileUpload.require_bounded((*self.attached_files, upload))
        except ValueError as error:
            self.show_failure(f"{name} not attached: {error}")
            return
        self.attached_files = (*self.attached_files, upload)
        self.show_attached()

    def detach_file(self, position: int) -> None:
        files = self.attached_files
        self.attached_files = files[:position] + files[position + 1:]
        self.show_attached()

    def take_files(self) -> tuple[FileUpload, ...]:
        """The files the message being sent carries; the composer holds none after."""
        files, self.attached_files = self.attached_files, ()
        self.show_attached()
        return files

    def restore(self, draft) -> None:
        """A send that did not land returns its files with its text."""
        super().restore(draft)
        self.attached_files = (*self.attached_files, *draft.files)
        self.show_attached()

    @staticmethod
    def chip_label(upload: FileUpload) -> str:
        return f"{upload.name} · {file_size(upload.size)}"
