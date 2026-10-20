"""One declared conversation value owns its destination and history behavior."""

from __future__ import annotations
import asyncio
from abc import abstractmethod
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, ClassVar
from agent_comms.historical_views import ChannelDisplayHistory, ConversationHistoryView, DMDisplayHistory
from agent_comms.declared_family import DeclaredFamily
from agent_comms.comms import Comms
from agent_comms.message_page import MessagePage, PageBounds
from textual.app import ComposeResult
from toad.widgets.input_delivery import InputDeliveryBar
from toad.widgets.native_history import NativeHistory
from toad.widgets.session_details import ConversationSessionDetails
from toad.widgets.channel_activity import ChannelActivity
from agent_comms.channel_targets import ThreadTarget
from toad.widgets.sidebar_tree import UnpaintedChannel

if TYPE_CHECKING:
    from toad.wire_history import WireSource


@dataclass(frozen=True)
class ConversationKind(DeclaredFamily, affix="Conversation"):
    target: str
    history_view: ClassVar[type[ConversationHistoryView]]

    def threads_needed(self, snapshot, me):
        return ()

    def channels_needed(self, root):
        return ()

    @classmethod
    def view_identity(cls, key):
        return key

    @classmethod
    @abstractmethod
    def page(cls, source: WireSource, bounds: PageBounds) -> MessagePage: ...

    @abstractmethod
    def resolve(self, comms: Comms, me: str) -> tuple[str, ConversationKind]: ...

    def label(self) -> str:
        return self.target

    def historical_thread(self) -> str | None:
        return None

    @classmethod
    async def toggle_irc(cls, screen) -> None:
        from toad.navigation_target import FeedTarget

        await screen.open_sidebar_target(FeedTarget())

    @classmethod
    async def toggle_dm(cls, screen) -> None:
        await screen.action_back_to_agent()
        screen.app.session_navigation.direct_messages()

    def unread(self, observation):
        return observation.channel_unread(self.target)

    def placeholder(self):
        return f"Message {self.target}"

    def send_target(self):
        return self.target

    def read_only(self, comms):
        return False

    @classmethod
    @abstractmethod
    async def update_mentions(cls, view, comms) -> None: ...

    @abstractmethod
    async def status_text(self, comms, *, read_only: bool) -> str: ...

    def activity_members(self, model):
        return (self.target,)

    def active_members(self, model):
        return tuple(model.threads.rows[name] for name in self.activity_members(model)
                     if model.threads.rows[name].active)

    @classmethod
    def activity_details(cls, name):
        row = ConversationSessionDetails(
            ThreadTarget(name), history=NativeHistory(), delivery=InputDeliveryBar(), status_source=lambda: row.row)
        return row

    @classmethod
    def compose_activity(cls, view) -> ComposeResult:
        view.thread_activity = cls.activity_details(view.conversation.target)
        yield view.thread_activity

    @abstractmethod
    def prompt(self): ...

    @classmethod
    def seen_page(cls, history, seen):
        """Acknowledge only visible fragments using their original page's proof."""
        if not seen:
            return None
        page = seen[0].evidence
        marked = tuple(fragment for fragment in seen if fragment.evidence is page)
        return page.select(fragment.message.seq for fragment in marked), marked


class ChannelConversation(ConversationKind):
    history_view = ChannelDisplayHistory

    def activity_members(self, model):
        return model.channels.rows.get(self.target, UnpaintedChannel(self.target)).members

    def channels_needed(self, root):
        return ((root, self.target),)

    @classmethod
    def view_identity(cls, key):
        from toad.session_tracker import ChannelViewAddress
        return ChannelViewAddress(key.root, key.conversation)

    @classmethod
    def page(cls, source: WireSource, bounds: PageBounds) -> MessagePage:
        return source.comms.views.channel_display_page(
            source.conversation.target, viewer=source.viewer, bounds=bounds)

    def resolve(self, comms: Comms, me: str) -> tuple[str, ConversationKind]:
        if me in comms.registry:
            me = comms.registry.require(me).name
        target = comms.bus.require_channel(self.target).name
        return me, self if target == self.target else replace(self, target=target)

    @classmethod
    def compose_activity(cls, view) -> ComposeResult:
        yield ChannelActivity(view)

    async def status_text(self, comms, *, read_only: bool) -> str:
        return "Read-only saved view" if read_only else ""

    def prompt(self):
        from toad.widgets.channel_prompt import ChannelPrompt

        return ChannelPrompt(placeholder=self.placeholder())

    def read_only(self, comms):
        return comms.bus.require_channel(self.target).read_only

    @classmethod
    async def update_mentions(cls, view, comms):
        from toad.widgets.channel_prompt import ChannelPrompt

        # Mention completion consumes the observer's membership snapshot,
        # not another registry/catalog read after every channel page.
        history = view.message_history
        source = history.source_snapshot()
        conversation = view.conversation
        access = view.app.coordination_access
        answer = await access.current_sidebar()
        snapshot = answer.require_snapshot()
        observed = access.observation
        if not observed.uses(comms):
            raise ValueError("Channel mentions belong to another Comms service")
        mentions = await view.app.preparation.run_thread(snapshot.mention_candidates, conversation.target)
        if not await history.source_is_current(source) or view.conversation != conversation:
            return
        view.query_one(ChannelPrompt).set_mention_candidates(mentions)


class DmConversation(ConversationKind):
    history_view = DMDisplayHistory

    def historical_thread(self) -> str:
        return self.target

    @classmethod
    async def toggle_dm(cls, screen) -> None:
        await screen.action_back_to_agent()

    def threads_needed(self, snapshot, me):
        return (snapshot.require(me).incarnation, snapshot.require(self.target).incarnation)

    def unread(self, observation):
        return observation.bus_unread(self.target)

    @classmethod
    def page(cls, source: WireSource, bounds: PageBounds) -> MessagePage:
        return source.comms.views.dm_display_page(
            source.conversation.target, worktree=str(source.project), bounds=bounds)

    def resolve(self, comms: Comms, me: str) -> tuple[str, ConversationKind]:
        target = comms.registry.require(self.target).name
        return comms.registry.require(me).name, self if target == self.target else replace(self, target=target)

    def label(self) -> str:
        return f"@{self.target}"

    @classmethod
    async def update_mentions(cls, view, comms) -> None:
        """Direct-message composers have no channel mention roster."""

    def prompt(self):
        from toad.widgets.prompt import MessagePrompt

        return MessagePrompt(placeholder=self.placeholder())

    async def status_text(self, comms, *, read_only: bool) -> str:
        return (await asyncio.to_thread(comms.configuration.answer, self.target)).status_label


class IrcConversation(ChannelConversation):
    @classmethod
    async def toggle_irc(cls, screen) -> None:
        await screen.action_back_to_agent()

    def label(self) -> str:
        return f"{self.target} · all comms"

    def placeholder(self):
        return "Message #all (broadcast)"

    def send_target(self):
        from toad.constants import ALL_COMMS_TARGET

        return ALL_COMMS_TARGET
