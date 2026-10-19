"""One declared conversation family owns history reads and route preparation."""

from __future__ import annotations
import asyncio
from abc import abstractmethod
from typing import TYPE_CHECKING, ClassVar
from agent_comms.historical_views import ChannelDisplayHistory, ConversationHistoryView, DMDisplayHistory
from agent_comms.declared_family import DeclaredFamily
from agent_comms.comms import Comms
from agent_comms.message_page import MessagePage, PageBounds
from textual.app import ComposeResult
from toad.widgets.native_history import NativeHistory
from toad.widgets.session_details import ConversationSessionDetails
from toad.widgets.channel_activity import ChannelActivity
from agent_comms.channel_targets import ThreadTarget
from toad.widgets.sidebar_tree import UnpaintedChannel

if TYPE_CHECKING:
    from toad.wire_history import WireSource


class ConversationKind(DeclaredFamily, affix="Conversation"):
    history_view: ClassVar[type[ConversationHistoryView]]

    @classmethod
    def threads_needed(cls, snapshot, me, target):
        return ()

    @classmethod
    def channels_needed(cls, root, target):
        return ()

    @classmethod
    def view_identity(cls, key):
        return key

    @classmethod
    @abstractmethod
    def page(cls, source: WireSource, bounds: PageBounds) -> MessagePage: ...

    @classmethod
    @abstractmethod
    def resolve(cls, comms: Comms, me: str, target: str) -> tuple[str, str]: ...

    @classmethod
    def label(cls, target: str) -> str:
        return target

    @classmethod
    def historical_thread(cls, target: str) -> str | None:
        return None

    @classmethod
    async def toggle_irc(cls, screen) -> None:
        from toad.navigation_target import FeedTarget

        await screen.open_sidebar_target(FeedTarget())

    @classmethod
    async def toggle_dm(cls, screen) -> None:
        await screen.action_back_to_agent()
        screen.app.session_navigation.direct_messages()

    @classmethod
    def unread(cls, observation, target):
        return observation.channel_unread(target)

    @classmethod
    def placeholder(cls, target):
        return f"Message {target}"

    @classmethod
    def send_target(cls, target):
        return target

    @classmethod
    def read_only(cls, comms, target):
        return False

    @classmethod
    @abstractmethod
    async def update_mentions(cls, view, comms) -> None: ...

    @classmethod
    @abstractmethod
    async def status_text(cls, comms, target, *, read_only: bool) -> str: ...

    @classmethod
    def activity_members(cls, model, target):
        return (target,)

    @classmethod
    def active_members(cls, model, target):
        return tuple(model.threads.rows[name] for name in cls.activity_members(model, target)
                     if model.threads.rows[name].active)

    @classmethod
    def activity_details(cls, name):
        row = ConversationSessionDetails(
            ThreadTarget(name), history=NativeHistory(), status_source=lambda: row.row)
        return row

    @classmethod
    def compose_activity(cls, view) -> ComposeResult:
        view.thread_activity = cls.activity_details(view.target)
        yield view.thread_activity

    @classmethod
    @abstractmethod
    def prompt(cls, target): ...

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

    @classmethod
    def activity_members(cls, model, target):
        return model.channels.rows.get(target, UnpaintedChannel(target)).members

    @classmethod
    def channels_needed(cls, root, target):
        return ((root, target),)

    @classmethod
    def view_identity(cls, key):
        from toad.session_tracker import ChannelViewAddress
        return ChannelViewAddress(key.root, key.target, cls)

    @classmethod
    def page(cls, source: WireSource, bounds: PageBounds) -> MessagePage:
        return source.comms.views.channel_display_page(
            source.target, viewer=source.viewer, bounds=bounds)

    @classmethod
    def resolve(cls, comms: Comms, me: str, target: str) -> tuple[str, str]:
        if me in comms.registry:
            me = comms.registry.require(me).name
        return me, comms.bus.require_channel(target).name

    @classmethod
    def compose_activity(cls, view) -> ComposeResult:
        yield ChannelActivity(view)

    @classmethod
    async def status_text(cls, comms, target, *, read_only: bool) -> str:
        return "Read-only saved view" if read_only else ""

    @classmethod
    def prompt(cls, target):
        from toad.widgets.channel_prompt import ChannelPrompt

        return ChannelPrompt(placeholder=cls.placeholder(target))

    @classmethod
    def read_only(cls, comms, target):
        return comms.bus.require_channel(target).read_only

    @classmethod
    async def update_mentions(cls, view, comms):
        from toad.widgets.channel_prompt import ChannelPrompt

        # Mention completion consumes the observer's membership snapshot,
        # not another registry/catalog read after every channel page.
        history = view.message_history
        source = history.source_snapshot()
        target = view.target
        access = view.app.coordination_access
        answer = await access.current_sidebar()
        snapshot = answer.require_snapshot()
        observed = access.observation
        if not observed.uses(comms):
            raise ValueError("Channel mentions belong to another Comms service")
        mentions = await view.app.preparation.run_thread(snapshot.mention_candidates, target)
        if not await history.source_is_current(source) or view.target != target:
            return
        view.query_one(ChannelPrompt).set_mention_candidates(mentions)


class DmConversation(ConversationKind):
    history_view = DMDisplayHistory

    @classmethod
    def historical_thread(cls, target: str) -> str:
        return target

    @classmethod
    async def toggle_dm(cls, screen) -> None:
        await screen.action_back_to_agent()

    @classmethod
    def threads_needed(cls, snapshot, me, target):
        return (snapshot.require(me).incarnation, snapshot.require(target).incarnation)

    @classmethod
    def unread(cls, observation, target):
        return observation.bus_unread(target)

    @classmethod
    def page(cls, source: WireSource, bounds: PageBounds) -> MessagePage:
        return source.comms.views.dm_display_page(
            source.target, worktree=str(source.project), bounds=bounds)

    @classmethod
    def resolve(cls, comms: Comms, me: str, target: str) -> tuple[str, str]:
        return comms.registry.require(me).name, comms.registry.require(target).name

    @classmethod
    def label(cls, target: str) -> str:
        return f"@{target}"

    @classmethod
    async def update_mentions(cls, view, comms) -> None:
        """Direct-message composers have no channel mention roster."""

    @classmethod
    def prompt(cls, target):
        from toad.widgets.prompt import MessagePrompt

        return MessagePrompt(placeholder=cls.placeholder(target))

    @classmethod
    async def status_text(cls, comms, target, *, read_only: bool) -> str:
        return (await asyncio.to_thread(comms.configuration.answer, target)).status_label


class IrcConversation(ChannelConversation):
    @classmethod
    async def toggle_irc(cls, screen) -> None:
        await screen.action_back_to_agent()

    @classmethod
    def label(cls, target: str) -> str:
        return f"{target} · all comms"

    @classmethod
    def placeholder(cls, target):
        return "Message #all (broadcast)"

    @classmethod
    def send_target(cls, target):
        from toad.constants import ALL_COMMS_TARGET

        return ALL_COMMS_TARGET
