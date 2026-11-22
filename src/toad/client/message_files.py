"""The files a message carries, in Toad: what a message composer attaches and sends, and what
a history draws under each message. No toolkit here.

Attaching: the attach action opens the picker the `ui.input.file_picker` setting names. Each
frontend answers only its pickers and how it draws the attached files: Qt's composer opens a
file dialog (on Android, the system's own file picker) or its path search, and Textual's
prompt opens its terminal pickers. A picked file becomes the upload Core checks again. The
files ride the submission with the text, and a send that does not land returns them to the
composer with its draft.

A history draws the files under each message through toad.client.message_file_links.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from abc import abstractmethod
from pathlib import Path

from agent_comms.messaging.message_files import (
    MAX_MESSAGE_FILE_BYTES,
    FileUpload,
)
from agent_comms.nominal.declared_choice import DeclaredChoice, TitledChoice
from formbridge.operations import ExclusiveKind, OperationKind

from toad.client.input_decision import InputAccepted, InputDecision
from toad.client.message_file_links import file_size
from toad.client.prompt_composer import PromptComposer
from toad.client.submission import ComposeAccess


class FilePicker(DeclaredChoice, affix="FilePicker"):
    """Which picker the attach action opens; each member names the composer's own."""

    @classmethod
    @abstractmethod
    def open(cls, composer: MessagePromptComposer) -> None: ...


class WindowFilePicker(TitledChoice, FilePicker):
    """The platform's file dialog. A phone shows its own chooser: the apps that give a file
    (its storage, photos and cloud drives) and the camera."""

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


class FileSearch(OperationKind, ExclusiveKind):
    """A path search picker listing or ranking the project's paths; a newer one replaces it."""


class AttachedFileChip:
    """One attached file as its composer draws it: its caption, and taking it off. Qt's and
    Textual's chip widgets inherit it; a plain mixin, as the toolkits' metaclasses need."""

    composer: MessagePromptComposer
    position: int

    def show_file(self, composer: MessagePromptComposer, position: int) -> None:
        self.composer, self.position = composer, position

    @property
    def caption(self) -> str:
        """Named apart from the toolkits' own: Textual's Button renders `label`."""
        return self.composer.chip_label(self.composer.attached_files[self.position])

    def take_off(self) -> None:
        """Named apart from the toolkits' own: Textual's `Widget.remove` leaves the DOM."""
        self.composer.detach_file(self.position)


class MessagePromptComposer(PromptComposer):
    """A message composer: always the agent glyph, every input accepted, and the files it
    sends with the text."""

    attached_files: tuple[FileUpload, ...] = ()
    takes_files: bool = True
    """Whether this composer's bus takes files, as its Core last answered (`ComposeAccess`);
    open until it answers, as every bus that takes files is."""

    @property
    def input_decision(self) -> InputDecision:
        """A message is accepted whether or not an agent is attached: its submission owner
        refuses a send it cannot make. An agent prompt asks its owner instead."""
        return InputAccepted()

    def prompt_symbol(self, text: str, shell_mode: bool) -> str:
        return self.settings.ui.input.agent_symbol

    def offer_files(self, takes_files: bool) -> None:
        if self.takes_files != takes_files:
            self.takes_files = takes_files
            self.show_files_offered()

    @abstractmethod
    def show_files_offered(self) -> None:
        """Offer Attach only while `takes_files`."""

    def files_refused(self) -> bool:
        """Whether this bus takes no files, having said so: the one refusal, for the attach
        key before it opens a picker and for every file that arrives."""
        if not self.takes_files:
            self.show_failure(ComposeAccess.files_refused_reason)
        return not self.takes_files

    def attach_file(self) -> None:
        """The attach action: the picker this composer's settings name opens, on a bus that
        takes files. A key pressed before the bus answered meets the reason instead."""
        if not self.files_refused():
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

    @property
    def read_limit(self) -> int:
        """The most bytes a picker reads of one file: one past what still fits, so an
        oversized file is refused below without being read whole."""
        return MAX_MESSAGE_FILE_BYTES - sum(upload.size for upload in self.attached_files) + 1

    async def attach_path(self, path: Path) -> None:
        """A picker chose a file on this machine: read at most `read_limit` of it and attach it."""
        limit = self.read_limit

        def read() -> bytes:
            with path.open("rb") as source:
                return source.read(limit)

        try:
            content = await asyncio.to_thread(read)
        except OSError as error:
            self.show_failure(f"{path.name} not attached: {error.strerror or error}")
            return
        self.file_picked(path.name, content)

    def file_picked(self, name: str, content: bytes, mime_type: str = "") -> None:
        """A file reached this message, from a picker or a paste: attach it, or say why it
        cannot go. A bus that takes no files says so here, whichever way the file came."""
        if self.files_refused():
            return
        try:
            upload = FileUpload.of(
                name, mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream", content)
            FileUpload.require_bounded((*self.attached_files, upload))
        except ValueError as error:
            self.show_failure(f"{name} not attached: {error}")
            return
        self.attached_files = (*self.attached_files, upload)
        self.show_attached()

    async def png_pasted(self, data: bytes) -> str:
        """A pasted image rides the message as a file and leaves nothing in the text. A
        message's readers are on other machines, where a path on this one names nothing:
        a screenshot pasted into #claude reached every teammate as one line of path."""
        self.file_picked(f"clipboard-{hashlib.sha256(data).hexdigest()[:12]}.png", data, "image/png")
        return ""

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
