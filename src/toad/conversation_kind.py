"""Conversation values own stable destinations; snapshots own their current names."""

from __future__ import annotations

from toad.session_actions import ReturnToViewAction

import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.channel_targets import (
    ChannelTarget,
    IncarnationThreadTarget,
    NamedTarget,
    ThreadTarget,
)
from agent_comms.channels import AllChannel
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import (
    CommsChannelTool, CommsConversationPageTool, CommsThreadConfigurationTool,
)
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.display_references import (
    RetiredThreadReference, ThreadDisplayReference, ThreadNames, ThreadReferenceReader,
)
from agent_comms.message_page import MessagePage, PageBounds
from agent_comms.projects.checkouts import Checkout
from agent_comms.thread_identity import ThreadIncarnation
from textual.app import ComposeResult

from toad.bus_submission import MessageDestination
from toad.bus_submission import SubmissionOwner
from toad.widgets.channel_prompt import ChannelPrompt
from toad.widgets.prompt import MessagePrompt
from toad.referenced_core import ReferencedCore
from toad.status_thread import NoStatusThread, StatusThread
from toad.widgets.channel_activity import ChannelActivity
from toad.widgets.session_details import ConversationSessionDetails
from toad.widgets.sidebar_tree import UnpaintedChannel
from toad.comms_root import CoordinationAccess
from toad.session_tracker import CommsViewKey
from toad.session_tracker import ChannelViewAddress

if TYPE_CHECKING:
    from agent_comms.ui_model.sidebar import SidebarModel, SidebarObservation

    from toad.screens.comms import CommsScreen
    from toad.screens.historical_sessions import HistoricalSessions
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.wire_history import WireHistory
    from toad.wire_history import WireSource


@dataclass(frozen=True)
class ConversationKind(MessageDestination, DeclaredFamily, affix="Conversation"):
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

    def threads_needed(self, source: ReferencedCore, me: str):
        return ()

    def channels_needed(self, root: str):
        return ()

    @classmethod
    def view_identity(cls, key: CommsViewKey):
        return key

    def page(self, source: WireSource, bounds: PageBounds) -> MessagePage:
        """Every conversation reads its page through the request a remote UI sends too."""
        return source.core.call(CommsConversationPageTool(
            conversation=self.retained_target(), project=source.project, bounds=bounds))

    @classmethod
    @abstractmethod
    def resolve(cls, source: ReferencedCore, me: str, name: str) -> ResolvedConversation:
        """Resolve `name` against the source's registry, the read every opening shares."""

    def label(self, references: ThreadNames) -> str:
        return self.destination(references).name

    def status_thread(self, root: Path, access: CoordinationAccess) -> StatusThread:
        return NoStatusThread()

    def historical_sessions(self, create_view: partial[HistoricalSessions], references: ThreadNames):
        return create_view()

    @classmethod
    async def toggle_irc(cls, screen: CommsScreen) -> None:
        from toad.navigation_target import FeedTarget

        await screen.open_sidebar_target(FeedTarget())

    @classmethod
    async def toggle_dm(cls, screen: CommsScreen) -> None:
        await ReturnToViewAction().apply(screen)
        screen.app.session_navigation.direct_messages()

    def unread(self, observation: SidebarObservation):
        return observation.channel_unread(self.retained_target().name)

    def send_target(self) -> NamedTarget:
        return self.retained_target()

    def read_only(self, core: CoreAccess) -> bool:
        """A conversation takes the owner's input unless its Core says otherwise."""
        return False

    @classmethod
    @abstractmethod
    async def update_mentions(cls, view: CommsChatView, source: ReferencedCore) -> None: ...

    @abstractmethod
    async def status_text(self, source: ReferencedCore, *, read_only: bool) -> str: ...

    def activity_members(self, model: SidebarModel):
        return (self.destination(model.observation.thread_names()).name,)

    def active_members(self, model: SidebarModel):
        return tuple(
            model.threads.rows[name] for name in self.activity_members(model) if model.threads.rows[name].active
        )

    @classmethod
    @abstractmethod
    def compose_activity(cls, view: CommsChatView) -> ComposeResult: ...

    @abstractmethod
    def prompt(self, project: Checkout, *, submissions: SubmissionOwner): ...

    @classmethod
    def seen_page(cls, history: WireHistory, seen):
        """Acknowledge visible fragments using their original page's proof."""
        if not seen:
            return None
        page = seen[0].evidence
        marked = tuple(fragment for fragment in seen if fragment.evidence is page)
        return page.select(fragment.message.seq for fragment in marked), marked


@dataclass(frozen=True)
class ResolvedConversation:
    viewer: str
    conversation: ConversationKind


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

    @classmethod
    def compose_activity(cls, view: CommsChatView) -> ComposeResult:
        yield ChannelActivity(view)

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
    async def update_mentions(cls, view: CommsChatView, source: ReferencedCore):
        history = view.message_history
        shown = history.source_snapshot()
        conversation = view.conversation
        access = view.app.coordination_access
        answer = await access.current_sidebar()
        snapshot = answer.require_snapshot()
        if not access.observation.observes(source.root):
            raise ValueError("Channel mentions belong to another Core root")
        mentions = await view.app.preparation.run_thread(
            snapshot.mention_candidates,
            conversation.destination(snapshot.references).name,
        )
        if not await history.source_is_current(shown) or view.conversation != conversation:
            return
        # Mentions are read in the chat-labels worker, which runs after the drawing work
        # and can take seconds on a busy bus (comms_chat.py:265). The composer can be
        # removed in that window, and a view with no composer has nothing to tell: the
        # query answers membership, so no match is not an exception.
        for prompt in view.query(ChannelPrompt):
            prompt.set_mention_candidates(mentions)


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

    def historical_sessions(self, create_view: partial[HistoricalSessions], references: ThreadNames):
        return create_view(name=self.destination(references).name)

    @classmethod
    async def toggle_dm(cls, screen: CommsScreen) -> None:
        await ReturnToViewAction().apply(screen)

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
    async def update_mentions(cls, view: CommsChatView, source: ReferencedCore) -> None:
        """Direct-message composers have no channel mention roster."""

    @classmethod
    def compose_activity(cls, view) -> ComposeResult:
        view.thread_activity = ConversationSessionDetails(view.conversation.peer)
        yield view.thread_activity

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
    async def toggle_irc(cls, screen: CommsScreen) -> None:
        await ReturnToViewAction().apply(screen)

    def label(self, references: ThreadNames) -> str:
        return f"{self.target.name} · all comms"

    initial_placeholder = "Message #all (broadcast)"

    def send_target(self) -> ChannelTarget:
        return AllChannel.target()
