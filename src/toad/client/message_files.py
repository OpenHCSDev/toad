"""The files a message carries, as a history draws them: one chip per file under the
message's text, each a link to the read that returns the file's bytes.

A page learns its messages' files from Core beside the page, one comms_message_files read
for each conversation the page holds, never one per message. The read names the
conversation and the participant reading it, so Core returns only files of messages that
reader may read. No toolkit: both frontends draw the chips as the spans they already draw,
and open them through `OpensLineLinks`.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from agent_comms.messaging.message_files import MessageFile, MessageFileContent
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import (
    CommsMessageFilesTool,
    CommsMessageFileTool,
)

from toad import paths
from toad.client.line_blocks import LineBlock, LineLink, MutedRole, Span, Spans


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
