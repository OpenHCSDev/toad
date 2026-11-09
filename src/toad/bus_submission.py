"""What a message source needs to queue its input: declared apart from the agent stack, so a
transcript scope or page source can start a bus send without importing ACP."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from agent_comms.messaging.channel_targets import NamedTarget
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.transport.request import CoreAccess

from toad.input_decision import InputDecision, InputRefused


class SubmissionStart(ABC):
    """The result of acquiring a submission's source, not an optional request."""

    @abstractmethod
    async def prepare(self): ...


class SubmittedText(ABC):
    """Text the owner submitted, exactly as typed; its request sends it stripped."""

    source_text: str

    @property
    def text(self) -> str:
        return self.source_text.strip()


class MessageDestination(ABC):
    """What a bus send asks of the conversation it writes to; every conversation kind is one."""

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
