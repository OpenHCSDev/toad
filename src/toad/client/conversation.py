"""Shared conversation identity and Core-read behavior.

The channel, direct-message and #all kinds own stable destinations, page reads,
sidebar interest, member resolution, status and the feed toggles here, and pick which
activity strip and prompt their view draws; each toolkit's view draws them.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from agent_comms.messaging.channel_targets import (
    ChannelTarget,
    IncarnationThreadTarget,
    NamedTarget,
    ThreadTarget,
)
from agent_comms.messaging.channels import AllChannel
from agent_comms.messaging.display_references import (
    RetiredThreadReference,
    ThreadDisplayReference,
    ThreadNames,
    ThreadReferenceReader,
)
from agent_comms.messaging.mentions import MentionCandidate
from agent_comms.messaging.message_page import MessagePage, PageBounds
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.transport.request import CoreAccess
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.transport.tools.sidebar import (
    CommsChannelTool,
    CommsConversationPageTool,
    CommsThreadConfigurationTool,
)
from agent_comms.ui_model.sidebar import SidebarModel, SidebarObservation

from toad.client.submission import MessageDestination
from toad.client.conversation_capabilities import (
    ConversationActivity,
    ConversationNavigation,
    ConversationSource,
)
from toad.client.referenced_core import ReferencedCore
from toad.client.sidebar_models import UnpaintedChannel
from toad.status_thread import NoStatusThread, StatusThread


class ConversationKind(MessageDestination, DeclaredFamily, affix="Conversation"):
    """A conversation on the bus: identity, routing, Core reads, and which activity strip
    and prompt its view draws. Nothing here imports a toolkit."""

    @abstractmethod
    def compose_activity(self, view: ConversationActivity) -> Iterator: ...

    @abstractmethod
    def prompt(self, view: ConversationActivity): ...

    @property
    @abstractmethod
    def initial_label(self) -> str: ...

    @property
    @abstractmethod
    def input_scope(self) -> str: ...

    @abstractmethod
    def destination(self, references: ThreadNames) -> NamedTarget: ...

    @abstractmethod
    def retained_target(self) -> NamedTarget: ...

    def sidebar_threads(self):
        return ()

    def threads_needed(self, source, me: str):
        return ()

    def channels_needed(self, root: str):
        return ()

    @classmethod
    async def toggle_irc(cls, screen: ConversationNavigation) -> None:
        await screen.show_feed()

    @classmethod
    async def toggle_dm(cls, screen: ConversationNavigation) -> None:
        await screen.show_direct_messages()

    @classmethod
    def view_identity(cls, key: CommsViewKey):
        return key

    def page(self, source: ConversationSource, bounds: PageBounds) -> MessagePage:
        return source.core.call(CommsConversationPageTool(
            conversation=self.retained_target(), project=source.project, bounds=bounds))

    @classmethod
    @abstractmethod
    def resolve(cls, source, me: str, name: str): ...

    def label(self, references: ThreadNames) -> str:
        return self.destination(references).name

    def status_thread(self, root: Path, access) -> StatusThread:
        return NoStatusThread()

    def historical_sessions(self, create_view: partial, references: ThreadNames):
        return create_view()

    def unread(self, observation: SidebarObservation):
        return observation.channel_unread(self.retained_target().name)

    def send_target(self) -> NamedTarget:
        return self.retained_target()

    def read_only(self, core: CoreAccess) -> bool:
        return False

    @classmethod
    @abstractmethod
    async def update_mentions(cls, view: ConversationActivity, source) -> None: ...

    @abstractmethod
    async def status_text(self, source, *, read_only: bool) -> str: ...

    def activity_members(self, model: SidebarModel):
        return (self.destination(model.observation.thread_names()).name,)

    def active_members(self, model: SidebarModel):
        return tuple(
            model.threads.rows[name] for name in self.activity_members(model) if model.threads.rows[name].active
        )

    @staticmethod
    def activity_title(members) -> str:
        """The collapsed activity line under the composer: how many members are active and
        the first two of them."""
        if not members:
            return "0 active"
        names = ", ".join(row.name for row in members[:2])
        remaining = f" +{len(members) - 2}" if len(members) > 2 else ""
        return f"{len(members)} active · {names}{remaining}"

    @classmethod
    def seen_page(cls, seen):
        if not seen:
            return None
        page = seen[0].evidence
        marked = tuple(fragment for fragment in seen if fragment.evidence is page)
        return page.select(fragment.message.seq for fragment in marked), marked


@dataclass(frozen=True)
class CommsViewKey:
    """A conversation on one bus: its tab is the owner's view of it, whichever tab opened it."""

    root: str
    conversation: ConversationKind


@dataclass(frozen=True)
class ChannelViewAddress:
    root: str
    conversation: ConversationKind


@dataclass(frozen=True)
class ResolvedConversation:
    viewer: str
    conversation: ConversationKind


@dataclass(frozen=True)
class ChannelConversation(ConversationKind):
    target: ChannelTarget

    def compose_activity(self, view: ConversationActivity) -> Iterator:
        return view.compose_channel_activity()

    def prompt(self, view: ConversationActivity):
        return view.channel_prompt(self.initial_placeholder)

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

    async def status_text(self, source: ReferencedCore, *, read_only: bool) -> str:
        return self.read_only_reason if read_only else ""

    @property
    def initial_placeholder(self) -> str:
        return f"Message {self.target.name}"

    def read_only(self, core: CoreAccess) -> bool:
        return core.call(CommsChannelTool(name=self.target.name)).read_only

    @classmethod
    async def update_mentions(cls, view: ConversationActivity, source: ReferencedCore):
        await view.update_channel_mentions(source)

    def mention_candidates(self, answer: SidebarObservation) -> tuple[MentionCandidate, ...]:
        """The threads this channel's composer offers after an @, from the observer's
        current sidebar answer; it reads Core, so it runs off the UI loop."""
        snapshot = answer.require_snapshot()
        return snapshot.mention_candidates(self.destination(snapshot.references).name)


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

    def compose_activity(self, view: ConversationActivity) -> Iterator:
        return view.compose_peer_activity(self.peer)

    def prompt(self, view: ConversationActivity):
        return view.message_prompt()

    @property
    def input_scope(self) -> str:
        return self.peer.require_recorded().lookup

    def destination(self, references: ThreadNames) -> ThreadTarget:
        """Where a send goes: the peer's birth answers, so a successor reusing its name never
        receives the old peer's messages."""
        return references.thread(self.peer).target()

    def retained_target(self) -> IncarnationThreadTarget:
        return IncarnationThreadTarget(self.peer)

    def status_thread(self, root: Path, access) -> StatusThread:
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

    async def status_text(self, source: ReferencedCore, *, read_only: bool) -> str:
        """Core's configuration answer for the thread this DM names."""
        def read():
            thread = self.destination(source.references()).name
            return source.core.call(CommsThreadConfigurationTool(thread=thread)).status_label

        return await asyncio.to_thread(read)


class IrcConversation(ChannelConversation):
    """The #all feed, drawn as a channel."""

    @classmethod
    async def toggle_irc(cls, screen: ConversationNavigation) -> None:
        await screen.return_to_view()

    def label(self, references: ThreadNames) -> str:
        return f"{self.target.name} · all comms"

    initial_placeholder = "Message #all (broadcast)"

    def send_target(self) -> ChannelTarget:
        return AllChannel.target()
