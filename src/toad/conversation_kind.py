"""Conversation values own stable destinations; snapshots own their current names."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from agent_comms.channel_targets import (
    ChannelTarget,
    IncarnationThreadTarget,
    NamedTarget,
    ThreadTarget,
)
from agent_comms.channels import AllChannel
from agent_comms.comms import Comms
from agent_comms.declared_family import DeclaredFamily
from agent_comms.display_references import CurrentDisplayReferences
from agent_comms.historical_views import (
    ChannelDisplayHistory,
    ConversationHistoryView,
    DMDisplayHistory,
)
from agent_comms.message_page import MessagePage, PageBounds
from agent_comms.thread_identity import ThreadIncarnation
from textual.app import ComposeResult

from toad.status_thread import NoStatusThread, StatusThread
from toad.widgets.channel_activity import ChannelActivity
from toad.widgets.session_details import ConversationSessionDetails
from toad.widgets.sidebar_tree import UnpaintedChannel

if TYPE_CHECKING:
    from toad.wire_history import WireSource


@dataclass(frozen=True)
class ConversationKind(DeclaredFamily, affix="Conversation"):
    history_view: ClassVar[type[ConversationHistoryView]]

    @property
    @abstractmethod
    def initial_label(self) -> str: ...

    @property
    @abstractmethod
    def input_scope(self) -> str: ...

    @abstractmethod
    def destination(self, references: CurrentDisplayReferences) -> NamedTarget: ...

    @abstractmethod
    def retained_target(self) -> NamedTarget: ...

    def threads_needed(self, snapshot, me):
        return ()

    def channels_needed(self, root):
        return ()

    @classmethod
    def view_identity(cls, key):
        return key

    @abstractmethod
    def page(self, source: WireSource, bounds: PageBounds) -> MessagePage: ...

    @classmethod
    @abstractmethod
    def resolve(cls, comms: Comms, me: str, name: str) -> ResolvedConversation: ...

    def label(self, references: CurrentDisplayReferences) -> str:
        return self.destination(references).name

    def status_thread(self, root, access) -> StatusThread:
        return NoStatusThread()

    def historical_sessions(self, create_view, references):
        return create_view()

    @classmethod
    async def toggle_irc(cls, screen) -> None:
        from toad.navigation_target import FeedTarget

        await screen.open_sidebar_target(FeedTarget())

    @classmethod
    async def toggle_dm(cls, screen) -> None:
        await screen.action_back_to_agent()
        screen.app.session_navigation.direct_messages()

    def unread(self, observation):
        return observation.channel_unread(
            self.destination(observation.require_snapshot().references).name
        )

    def send_target(self) -> NamedTarget:
        return self.retained_target()

    def read_only(self, comms: Comms) -> bool:
        return False

    @classmethod
    @abstractmethod
    async def update_mentions(cls, view, comms: Comms) -> None: ...

    @abstractmethod
    async def status_text(self, comms: Comms, *, read_only: bool) -> str: ...

    def activity_members(self, model):
        return (self.destination(model.observation.require_snapshot().references).name,)

    def active_members(self, model):
        return tuple(
            model.threads.rows[name]
            for name in self.activity_members(model)
            if model.threads.rows[name].active
        )

    @classmethod
    @abstractmethod
    def compose_activity(cls, view) -> ComposeResult: ...

    @abstractmethod
    def prompt(self): ...

    @classmethod
    def seen_page(cls, history, seen):
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
    history_view = ChannelDisplayHistory

    @property
    def initial_label(self) -> str:
        return self.target.name

    @property
    def input_scope(self) -> str:
        return self.target.name

    def destination(self, references: CurrentDisplayReferences) -> ChannelTarget:
        return self.target

    def retained_target(self) -> ChannelTarget:
        return self.target

    def activity_members(self, model):
        return model.channels.rows.get(
            self.target.name, UnpaintedChannel(self.target.name)
        ).members

    def channels_needed(self, root):
        return ((root, self.target.name),)

    @classmethod
    def view_identity(cls, key):
        from toad.session_tracker import ChannelViewAddress

        return ChannelViewAddress(key.root, key.conversation)

    def page(self, source: WireSource, bounds: PageBounds) -> MessagePage:
        return source.comms.views.channel_display_page(
            self.target.name,
            viewer=source.viewer, bounds=bounds,
        )

    @classmethod
    def resolve(cls, comms: Comms, me: str, name: str) -> ResolvedConversation:
        snapshot = comms.registry.snapshot()
        resolved = ChannelTarget(name).resolve(snapshot, comms.bus.require_channel)
        return ResolvedConversation(
            snapshot.canonical_name(me), cls(ChannelTarget(resolved.channel.name))
        )

    @classmethod
    def compose_activity(cls, view) -> ComposeResult:
        yield ChannelActivity(view)

    async def status_text(self, comms: Comms, *, read_only: bool) -> str:
        return "Read-only saved view" if read_only else ""

    @property
    def initial_placeholder(self) -> str:
        return f"Message {self.target.name}"

    def prompt(self):
        from toad.widgets.channel_prompt import ChannelPrompt

        return ChannelPrompt(placeholder=self.initial_placeholder)

    def read_only(self, comms: Comms) -> bool:
        return comms.bus.require_channel(self.target.name).read_only

    @classmethod
    async def update_mentions(cls, view, comms: Comms):
        from toad.widgets.channel_prompt import ChannelPrompt

        history = view.message_history
        source = history.source_snapshot()
        conversation = view.conversation
        access = view.app.coordination_access
        answer = await access.current_sidebar()
        snapshot = answer.require_snapshot()
        observed = access.observation
        if not observed.uses(comms):
            raise ValueError("Channel mentions belong to another Comms service")
        mentions = await view.app.preparation.run_thread(
            snapshot.mention_candidates,
            conversation.destination(snapshot.references).name,
        )
        if (
            not await history.source_is_current(source)
            or view.conversation != conversation
        ):
            return
        view.query_one(ChannelPrompt).set_mention_candidates(mentions)


@dataclass(frozen=True)
class DmConversation(ConversationKind):
    peer: ThreadIncarnation
    history_view = DMDisplayHistory
    initial_label = "Direct messages"

    @property
    def input_scope(self) -> str:
        return self.peer.require_recorded().lookup

    def destination(self, references: CurrentDisplayReferences) -> ThreadTarget:
        return ThreadTarget(references.thread(self.peer).name)

    def retained_target(self) -> IncarnationThreadTarget:
        return IncarnationThreadTarget(self.peer)

    def status_thread(self, root, access) -> StatusThread:
        return StatusThread.for_conversation(root, self, access)

    def historical_sessions(self, create_view, references):
        return create_view(name=self.destination(references).name)

    @classmethod
    async def toggle_dm(cls, screen) -> None:
        await screen.action_back_to_agent()

    def threads_needed(self, snapshot, me):
        return snapshot.require(me).incarnation, self.peer

    def unread(self, observation):
        return observation.bus_unread(
            self.destination(observation.require_snapshot().references).name
        )

    def page(self, source: WireSource, bounds: PageBounds) -> MessagePage:
        return source.comms.views.dm_display_page(
            self.retained_target(),
            worktree=str(source.project), bounds=bounds,
        )

    @classmethod
    def resolve(cls, comms: Comms, me: str, name: str) -> ResolvedConversation:
        snapshot = comms.registry.snapshot()
        resolved = ThreadTarget(name).resolve(snapshot, comms.bus.require_channel)
        return ResolvedConversation(
            snapshot.require(me).name, cls(resolved.thread.incarnation)
        )

    def label(self, references: CurrentDisplayReferences) -> str:
        return f"@{self.destination(references).name}"

    @classmethod
    async def update_mentions(cls, view, comms: Comms) -> None:
        """Direct-message composers have no channel mention roster."""

    @classmethod
    def compose_activity(cls, view) -> ComposeResult:
        view.thread_activity = ConversationSessionDetails(view.conversation.peer)
        yield view.thread_activity

    def prompt(self):
        from toad.widgets.prompt import MessagePrompt

        return MessagePrompt()

    async def status_text(self, comms: Comms, *, read_only: bool) -> str:
        def read():
            references = CurrentDisplayReferences(
                str(comms.root), registry=comms.registry.snapshot()
            )
            return comms.configuration.answer(self.destination(references).name)

        return (await asyncio.to_thread(read)).status_label


class IrcConversation(ChannelConversation):
    @classmethod
    async def toggle_irc(cls, screen) -> None:
        await screen.action_back_to_agent()

    def label(self, references: CurrentDisplayReferences) -> str:
        return f"{self.target.name} · all comms"

    initial_placeholder = "Message #all (broadcast)"

    def send_target(self) -> ChannelTarget:
        return AllChannel.target()
