"""Conversation values own stable destinations; snapshots own their current names."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from agent_comms.messaging.channel_targets import (
    ChannelTarget,
    IncarnationThreadTarget,
    ThreadTarget,
)
from agent_comms.messaging.channels import AllChannel
from agent_comms.messaging.display_references import (
    RetiredThreadReference,
    ThreadDisplayReference,
    ThreadNames,
    ThreadReferenceReader,
)
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import (
    CommsChannelTool,
    CommsThreadConfigurationTool,
)
from agent_comms.ui_model.sidebar import SidebarModel, SidebarObservation
from textual.app import ComposeResult

from toad.bus_submission import SubmissionOwner
from toad.client.connection import CoordinationAccess
from toad.client.conversation import ResolvedConversation, SharedConversationKind
from toad.conversation_capabilities import (
    ConversationActivity,
    ConversationNavigation,
)
from toad.referenced_core import ReferencedCore
from toad.session_tracker import ChannelViewAddress, CommsViewKey
from toad.sidebar_models import UnpaintedChannel
from toad.status_thread import StatusThread
from toad.widgets.channel_prompt import ChannelPrompt
from toad.widgets.prompt import MessagePrompt


@dataclass(frozen=True)
class ConversationKind(SharedConversationKind):
    """Native conversation with Textual-specific compose/prompt/toggle methods."""

    @classmethod
    async def toggle_irc(cls, screen: ConversationNavigation) -> None:
        await screen.show_feed()

    @classmethod
    async def toggle_dm(cls, screen: ConversationNavigation) -> None:
        await screen.show_direct_messages()

    @abstractmethod
    def compose_activity(self, view: ConversationActivity) -> ComposeResult: ...

    @abstractmethod
    def prompt(self, project: Checkout, *, submissions: SubmissionOwner): ...


@dataclass(frozen=True)
class ChannelConversation(ConversationKind):
    target: ChannelTarget

    @property
    def initial_label(self) -> str:
        return self.target.name

    @property
    def input_scope(self) -> str:
        return self.target.name

    def destination(self, references: ThreadNames) -> ChannelTarget:
        return self.target

    def retained_target(self) -> ChannelTarget:
        return self.target

    def activity_members(self, model: SidebarModel):
        return model.channels.rows.get(self.target.name, UnpaintedChannel(self.target.name)).members

    def channels_needed(self, root: str):
        return ((root, self.target.name),)

    @classmethod
    def view_identity(cls, key: CommsViewKey):

        return ChannelViewAddress(key.root, key.conversation)

    @classmethod
    def resolve(cls, source: ReferencedCore, me: str, name: str) -> ResolvedConversation:
        # The opening needs the channel's own declaration and the viewer's name, as a direct
        # message reads its two threads; resolving every member would read the whole registry.
        target = ChannelTarget(name)
        channel = source.core.call(CommsChannelTool(name=target.name))
        return ResolvedConversation(source.registry_for(me).canonical_name(me), cls(ChannelTarget(channel.name)))

    def compose_activity(self, view: ConversationActivity) -> ComposeResult:
        yield from view.compose_channel_activity()

    async def status_text(self, source: ReferencedCore, *, read_only: bool) -> str:
        return "Read-only saved view" if read_only else ""

    @property
    def initial_placeholder(self) -> str:
        return f"Message {self.target.name}"

    def prompt(self, project: Checkout, *, submissions: SubmissionOwner):
        return ChannelPrompt(project=project, placeholder=self.initial_placeholder, submissions=submissions)

    def read_only(self, core: CoreAccess) -> bool:
        return core.call(CommsChannelTool(name=self.target.name)).read_only

    @classmethod
    async def update_mentions(cls, view: ConversationActivity, source: ReferencedCore):
        await view.update_channel_mentions(source)


class PeerLabel(ThreadReferenceReader[str]):
    """A DM tab names its peer; a retired birth keeps its recorded name, marked gone."""

    def current(self, reference: ThreadDisplayReference) -> str:
        return f"@{reference.name}"

    def retired(self, reference: RetiredThreadReference) -> str:
        return f"@{reference.name} (gone)"


PEER_LABEL = PeerLabel()


@dataclass(frozen=True)
class DmConversation(ConversationKind):
    peer: ThreadIncarnation
    initial_label = "Direct messages"

    @property
    def input_scope(self) -> str:
        return self.peer.require_recorded().lookup

    def destination(self, references: ThreadNames) -> ThreadTarget:
        """Where a send goes: the peer's birth answers, so a successor reusing its name never
        receives the old peer's messages."""
        return references.thread(self.peer).target()

    def retained_target(self) -> IncarnationThreadTarget:
        return IncarnationThreadTarget(self.peer)

    def status_thread(self, root: Path, access: CoordinationAccess) -> StatusThread:
        return StatusThread.for_conversation(root, self, access)

    def historical_sessions[View](self, create_view: partial[View], references: ThreadNames) -> View:
        return create_view(name=self.destination(references).name)

    @classmethod
    async def toggle_dm(cls, screen: ConversationNavigation) -> None:
        await screen.return_to_view()

    def sidebar_threads(self):
        return (self.peer,)

    def threads_needed(self, source: ReferencedCore, me: str):
        return source.registry_for(me).require(me).incarnation, self.peer

    def unread(self, observation: SidebarObservation):
        """The peer's name and its count come from the observation's one cut, by birth."""
        return observation.peer_unread(self.peer)

    @classmethod
    def resolve(cls, source: ReferencedCore, me: str, name: str) -> ResolvedConversation:
        snapshot = source.registry_for(me, name)
        resolved = ThreadTarget(name).resolve(snapshot, lambda channel: source.core.call(CommsChannelTool(name=channel)))
        return ResolvedConversation(snapshot.require(me).name, cls(resolved.thread.incarnation))

    def label(self, references: ThreadNames) -> str:
        return references.thread(self.peer).read(PEER_LABEL)

    @classmethod
    async def update_mentions(cls, view: ConversationActivity, source: ReferencedCore) -> None:
        """Direct-message composers have no channel mention roster."""

    def compose_activity(self, view: ConversationActivity) -> ComposeResult:
        yield from view.compose_peer_activity(self.peer)

    def prompt(self, project: Checkout, *, submissions: SubmissionOwner):
        return MessagePrompt(project=project, submissions=submissions)

    async def status_text(self, source: ReferencedCore, *, read_only: bool) -> str:
        """Core's configuration answer for the thread this DM names."""
        def read():
            thread = self.destination(source.references()).name
            return source.core.call(CommsThreadConfigurationTool(thread=thread)).status_label

        return await asyncio.to_thread(read)


class IrcConversation(ChannelConversation):
    @classmethod
    async def toggle_irc(cls, screen: ConversationNavigation) -> None:
        await screen.return_to_view()

    def label(self, references: ThreadNames) -> str:
        return f"{self.target.name} · all comms"

    initial_placeholder = "Message #all (broadcast)"

    def send_target(self) -> ChannelTarget:
        return AllChannel.target()
