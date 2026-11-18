"""The files a message carries, in Toad: what a message composer attaches and sends, and what
a history draws under each message. No toolkit here.

Attaching: the attach action opens the picker the `ui.input.file_picker` setting names. Each
frontend answers only its pickers and how it draws the attached files: Qt's composer opens a
file dialog (on Android, the system's own file picker) or its path search, and Textual's
prompt opens its terminal pickers. A picked file becomes the upload Core checks again. The
files ride the submission with the text, and a send that does not land returns them to the
composer with its draft.

Drawing: a page learns its messages' files from Core beside the page, one
comms_message_files read for each conversation the page holds, never one per message. The
read names the conversation and the participant reading it, so Core returns only files of
messages that reader may read. Both frontends draw the chips as the spans they already
draw, and open them through `OpensLineLinks`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import mimetypes
from abc import abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from agent_comms.messaging.message_files import (
    MAX_MESSAGE_FILE_BYTES,
    FileUpload,
    MessageFile,
    MessageFileContent,
)
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import (
    CommsMessageFilesTool,
    CommsMessageFileTool,
)
from formbridge.operations import ExclusiveKind, OperationKind

from toad import paths
from toad.client.input_decision import InputAccepted, InputDecision
from toad.client.line_blocks import LineBlock, LineLink, MutedRole, Span, Spans
from toad.client.prompt_composer import PromptComposer


def file_size(size: int) -> str:
    """A byte count as a reader reads it: B under 1024, else one decimal in KB or MB."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


@dataclass(frozen=True, slots=True)
class FileReader:
    """Whose read a message's files are: the conversation they are read in (a #channel, or
    a DM's other participant) and the participant reading it."""

    conversation: str
    participant: str

    def files_of(self, core: CoreAccess, messages: tuple[MessageReference, ...]) -> tuple[MessageFile, ...]:
        return core.call(CommsMessageFilesTool(
            conversation=self.conversation, participant=self.participant, messages=messages)).files


@dataclass(frozen=True)
class MessageFileLink(LineLink):
    """One file of one message on one bus, and the reader its read names."""

    root: str
    conversation: str
    participant: str
    file: MessageFile

    @property
    def request(self) -> CommsMessageFileTool:
        return CommsMessageFileTool(
            conversation=self.conversation, participant=self.participant,
            message=self.file.message, position=self.file.position)

    def fetched(self, core: CoreAccess) -> Path:
        """The file's bytes, read from Core and kept where this machine opens them: under
        the data folder, by the file's digest, in its own name. Bytes that do not match the
        digest Core listed are refused, never kept."""
        return saved_copy(core.call(self.request))

    @property
    def chip(self) -> Span:
        return Span(f"[{self.file.name} · {file_size(self.file.size)}]", MutedRole, self)


@dataclass(frozen=True)
class PageFiles:
    """The files of one page's messages, as Core answered them for the page's readers."""

    links: tuple[tuple[MessageReference, tuple[MessageFileLink, ...]], ...] = ()

    @classmethod
    def read(cls, root: str, core: CoreAccess,
             readers: Iterable[tuple[MessageReference, FileReader]]) -> PageFiles:
        """One read per reader the page's messages name."""
        grouped: dict[FileReader, list[MessageReference]] = {}
        for reference, reader in readers:
            grouped.setdefault(reader, []).append(reference)
        links: dict[MessageReference, list[MessageFileLink]] = {}
        for reader, references in grouped.items():
            for file in reader.files_of(core, tuple(references)):
                links.setdefault(file.message, []).append(MessageFileLink(
                    str(root), reader.conversation, reader.participant, file))
        return cls(tuple((reference, tuple(found)) for reference, found in links.items()))

    def of(self, reference: MessageReference) -> tuple[MessageFileLink, ...]:
        for message, found in self.links:
            if message == reference:
                return found
        return ()


NO_PAGE_FILES = PageFiles()
"""A page read with no file store beside it: an attached history, or a draft not yet committed."""


def file_chips(links: tuple[MessageFileLink, ...]) -> tuple[LineBlock, ...]:
    """The line of chips under a message's text; a message with no files draws none."""
    if not links:
        return ()
    chips: list[Span] = []
    for link in links:
        chips.extend((Span("  "), link.chip) if chips else (link.chip,))
    return (Spans(tuple(chips)),)


def saved_copy(content: MessageFileContent) -> Path:
    data = base64.b64decode(content.data, validate=True)
    file = content.file
    if Path(file.name).name != file.name or file.name in {"", ".", ".."}:
        raise ValueError(f"{file.name!r} is not a file name this machine keeps.")
    if hashlib.sha256(data).hexdigest() != file.sha256:
        raise ValueError(f"{file.name} arrived with bytes that do not match its SHA-256.")
    folder = paths.get_data() / "message-files" / file.sha256[:16]
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / file.name
    if not path.is_file() or path.read_bytes() != data:
        staged = path.with_name(f".{file.name}.part")
        staged.write_bytes(data)
        staged.replace(path)
    return path


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
