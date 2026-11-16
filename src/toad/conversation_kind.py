"""Conversation values own stable destinations; snapshots own their current names."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass

from agent_comms.projects.checkouts import Checkout
from textual.app import ComposeResult

from toad.client.submission import SubmissionOwner
from toad.client.conversation import (
    SharedChannelConversation,
    SharedDmConversation,
    SharedIrcConversation,
    SharedConversationKind,
)
from toad.client.conversation_capabilities import (
    ConversationActivity,
)
from toad.widgets.channel_prompt import ChannelPrompt
from toad.widgets.prompt import MessagePrompt


@dataclass(frozen=True)
class ConversationKind(SharedConversationKind):
    """A conversation drawn by Textual: its activity strip and its prompt."""

    @abstractmethod
    def compose_activity(self, view: ConversationActivity) -> ComposeResult: ...

    @abstractmethod
    def prompt(self, project: Checkout, *, submissions: SubmissionOwner): ...


class ChannelConversation(SharedChannelConversation, ConversationKind):
    def compose_activity(self, view: ConversationActivity) -> ComposeResult:
        yield from view.compose_channel_activity()

    def prompt(self, project: Checkout, *, submissions: SubmissionOwner):
        return ChannelPrompt(project=project, placeholder=self.initial_placeholder, submissions=submissions)


class DmConversation(SharedDmConversation, ConversationKind):
    def compose_activity(self, view: ConversationActivity) -> ComposeResult:
        yield from view.compose_peer_activity(self.peer)

    def prompt(self, project: Checkout, *, submissions: SubmissionOwner):
        return MessagePrompt(project=project, submissions=submissions)


class IrcConversation(SharedIrcConversation, ChannelConversation):
    """The #all feed, drawn as a channel."""
