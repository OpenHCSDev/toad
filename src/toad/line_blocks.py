"""What a committed transcript fragment shows, independent of any frontend.

A fragment becomes a few line blocks. Blocks carry text and semantic roles;
a frontend maps roles to its own styles and renders the blocks. Nothing here
imports a terminal or rendering library.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    AgentTextTranscript, ContextTranscript, IncomingTranscript, SentTranscript,
    ThinkingTranscript, ToolTranscript, TranscriptEvent, UserTranscript,
)


class LineRole:
    """The meaning of a piece of text; frontends choose how each role looks."""


class TextRole(LineRole):
    """Ordinary message text."""


class MutedRole(LineRole):
    """Secondary text: summaries, collapsed disclosures."""


class ThinkingRole(MutedRole):
    """The model's visible reasoning."""


class UserRole(LineRole):
    pass


class AgentRole(LineRole):
    pass


class IncomingRole(LineRole):
    """A message received from another participant."""


class OutgoingRole(LineRole):
    """A message sent to another participant."""


class NoticeRole(LineRole):
    pass


class LineBlock:
    """One visual part of a fragment."""


@dataclass(frozen=True)
class Divider(LineBlock):
    """A rule naming the speaker; the frontend formats the time."""

    label: str
    role: type[LineRole]
    timestamp: float | None = None


@dataclass(frozen=True)
class Summary(LineBlock):
    """A single collapsed line, such as a tool call or coordination context."""

    text: str
    role: type[LineRole] = MutedRole


@dataclass(frozen=True)
class Gap(LineBlock):
    """One blank line between messages."""


@dataclass(frozen=True)
class Body(LineBlock):
    """Message text, optionally marked by a bar in another role; Markdown or plain."""

    text: str
    role: type[LineRole] = TextRole
    bar: type[LineRole] | None = None
    markdown: bool = True


class FragmentLineConsumer(MroDispatch):
    """Turn a fragment's events into line blocks, one handler per event family."""

    def __init__(self, *, show_divider: bool):
        self.show_divider = show_divider
        self.blocks: list[LineBlock] = []

    def divider(self, label: str, timestamp: float | None, role: type[LineRole]) -> None:
        if self.show_divider:
            self.blocks.append(Divider(label, role, timestamp))

    @handles(TranscriptEvent)
    def other(self, event: TranscriptEvent) -> None:
        """Events without visible text in committed history draw nothing."""

    @handles(UserTranscript)
    def user(self, event: UserTranscript) -> None:
        self.divider("User", event.timestamp, UserRole)
        self.blocks += [Body(event.text, bar=UserRole, markdown=False), Gap()]

    @handles(AgentTextTranscript)
    def agent(self, event: AgentTextTranscript) -> None:
        self.divider("Agent", event.timestamp, AgentRole)
        self.blocks += [Body(event.text), Gap()]

    @handles(ThinkingTranscript)
    def thinking(self, event: ThinkingTranscript) -> None:
        if event.text.strip():
            self.blocks += [Body(event.text, role=ThinkingRole), Gap()]

    @handles(IncomingTranscript)
    def incoming(self, event: IncomingTranscript) -> None:
        route = event.route
        targets = ", ".join(route.targets)
        self.divider(f"{route.sender} → {targets}" if targets else route.sender,
                     event.timestamp, IncomingRole)
        self.blocks += [Body(event.text, bar=IncomingRole), Gap()]

    @handles(SentTranscript)
    def sent(self, event: SentTranscript) -> None:
        reply = event.routing.reply if event.routing is not None else None
        targets = ", ".join(reply.targets) if reply is not None else ""
        self.divider(f"Sent → {targets}" if targets else "Sent", event.timestamp, OutgoingRole)
        self.blocks += [Body(event.text, bar=OutgoingRole), Gap()]

    @handles(ContextTranscript)
    def context(self, event: ContextTranscript) -> None:
        self.blocks.append(Summary("▶ Agent coordination context"))

    @handles(ToolTranscript)
    def tool(self, event: ToolTranscript) -> None:
        self.blocks.append(Summary(f"▶ {event.tool_name}"))
