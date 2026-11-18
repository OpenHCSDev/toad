"""What a message source needs to queue its input: declared apart from the agent stack, so a
transcript scope or page source can start a bus send without importing ACP."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from agent_comms.messaging.channel_targets import NamedTarget
from agent_comms.messaging.message_files import FileUpload
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import CommsMessageFilesTool

from toad.client.input_decision import InputDecision, InputRefused


class SubmissionStart(ABC):
    """The result of acquiring a submission's source, not an optional request."""

    @abstractmethod
    async def prepare(self): ...


class SubmittedText(ABC):
    """Text the owner submitted, exactly as typed, and the files attached to it; its request
    sends the text stripped."""

    source_text: str
    files: tuple[FileUpload, ...]

    @property
    def text(self) -> str:
        return self.source_text.strip()


@dataclass(frozen=True)
class ComposeAccess:
    """What compose may do in one conversation, as its Core answered: whether it is held
    (a read-only saved view), and whether its messages may carry files. A bus older than
    message files takes none: files and the read that lists them shipped together, so a
    Core that does not serve that read takes no upload either."""

    read_only: bool
    takes_files: bool

    files_refused_reason: ClassVar[str] = "This bus takes no files (its agent-comms predates them)"
    """Why a message carrying files is not sent here."""

    @property
    def block_reason(self) -> str:
        """Why compose is held here; empty while it is open."""
        return MessageDestination.read_only_reason if self.read_only else ""

    def refuses(self, draft: SubmittedText) -> bool:
        """A draft carrying files to a bus that takes none is refused before it is sent."""
        return bool(draft.files) and not self.takes_files


class MessageDestination(ABC):
    """What a bus send asks of the conversation it writes to; every conversation kind is one."""

    read_only_reason: ClassVar[str] = "Read-only saved view"
    """Why compose is held when read_only answers True."""

    def compose_access(self, core: CoreAccess) -> ComposeAccess:
        """What compose may do here, from this destination's Core; reads Core, so off the UI
        thread."""
        return ComposeAccess(self.read_only(core), core.serves(CommsMessageFilesTool))

    @abstractmethod
    def send_target(self) -> NamedTarget: ...

    @abstractmethod
    def read_only(self, core: CoreAccess) -> bool: ...


@dataclass(frozen=True)
class BusDestination(ABC):
    """Where a channel, inbox or CLI thread's message goes; the message source that builds
    it answers whether its view still shows it and what follows a delivered send."""

    root: str | Path
    conversation: MessageDestination

    @abstractmethod
    def shown(self) -> bool: ...

    @abstractmethod
    async def presented(self, sent: MessageReference) -> None: ...


class SubmissionOwner(ABC):
    """A view's pending submissions: a source starts its input here or refuses it here, and
    the view's prompt reads whether input is held and what the queue shows."""

    @property
    @abstractmethod
    def input_decision(self) -> InputDecision: ...

    @property
    @abstractmethod
    def holds_input(self) -> bool: ...

    @property
    @abstractmethod
    def queue_summary(self) -> str: ...

    @abstractmethod
    def start_bus(
        self, submission: SubmittedText, destination: BusDestination
    ) -> SubmissionStart: ...

    @abstractmethod
    def unbound(
        self, submission: SubmittedText, refusal: InputRefused
    ) -> SubmissionStart: ...
