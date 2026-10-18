"""One declared conversation family owns history reads and route preparation."""

from __future__ import annotations
from toad.widgets.presentation_window import NEWER_END

import asyncio
from dataclasses import replace
from abc import abstractmethod
from typing import TYPE_CHECKING, ClassVar
from agent_comms.historical_views import ChannelDisplayHistory, ConversationHistoryView, DMDisplayHistory
from agent_comms.declared_family import DeclaredFamily
from agent_comms.comms import Comms
from agent_comms.message_page import MessagePage, PageBounds
from agent_comms.presentation import ReadThrough
from textual.app import ComposeResult
from toad.widgets.native_history import NativeHistory
from toad.widgets.session_details import ConversationSessionDetails
from toad.widgets.channel_activity import ChannelActivity
from agent_comms.channel_targets import ThreadTarget

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
    def read_only(cls, catalog, target):
        return False

    @classmethod
    @abstractmethod
    async def update_mentions(cls, view, comms) -> None: ...

    @classmethod
    @abstractmethod
    async def status_text(cls, comms, target, *, read_only: bool) -> str: ...

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
    @abstractmethod
    def seen_page(cls, history, seen):
        """The page to mark read for the seen fragments and the fragments it settles, or None.

        Every fragment in `seen` still holds its page's read evidence.
        """

    @classmethod
    @abstractmethod
    async def mark_read(cls, comms, target, project, page): ...


class ChannelConversation(ConversationKind):
    history_view = ChannelDisplayHistory

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
        return me, comms.channels.catalog.read().resolve(target).name

    @classmethod
    def compose_activity(cls, view) -> ComposeResult:
        yield ChannelActivity(view)

    @classmethod
    async def status_text(cls, comms, target, *, read_only: bool) -> str:
        return "Read-only saved view" if read_only else ""

    @classmethod
    def prompt(cls, target):
        from toad.widgets.channel_prompt import ChannelPrompt

        return ChannelPrompt(simple_input=True, placeholder=cls.placeholder(target))

    @classmethod
    def read_only(cls, catalog, target):
        return catalog.resolve(target).read_only

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

    @classmethod
    def seen_page(cls, history, seen):
        if not seen:
            return None
        page = seen[0].evidence
        marked = tuple(fragment for fragment in seen if fragment.evidence is page)
        selected = {fragment.message.seq for fragment in marked}
        scope = page.display_scope
        return replace(
            page,
            messages=tuple(message for message in page.messages if message.seq in selected),
            display_scope=replace(scope, displayed=scope.displayed.select(selected)),
        ), marked

    @classmethod
    async def mark_read(cls, comms, target, project, page):
        from agent_comms.route_selection import implicit_root, run_selected_write

        assert page.display_scope is not None and page.newest_seq is not None
        await asyncio.to_thread(
            run_selected_write,
            comms.root,
            comms.views.mark_channel_view_read,
            target,
            worktree=project,
            mark=ReadThrough(page.newest_seq, page.display_scope),
            implicit=implicit_root(),
        )


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
        from toad.widgets.prompt import Prompt

        return Prompt(simple_input=True, placeholder=cls.placeholder(target))

    @classmethod
    async def status_text(cls, comms, target, *, read_only: bool) -> str:
        return (await asyncio.to_thread(comms.configuration.answer, target)).status_label

    @classmethod
    def seen_page(cls, history, seen):
        # Only the newest page marks a direct conversation read, and only as a
        # whole: its newest message and every message from the peer were seen.
        newest = history.pages[-1]
        page = newest.prepared.page.source
        if NEWER_END.visible_more(history) or page is None:
            return None
        painted = {fragment.message.seq for fragment in seen if fragment.evidence is page}
        if page.newest_seq not in painted:
            return None
        basis = page.display_basis
        if any(message.seq not in painted for message in page.messages
               if message.sender in basis.peer_names and message.target in basis.viewer_names):
            return None
        return replace(
            page,
            messages=tuple(message for message in page.messages if message.seq in painted),
            display_basis=replace(basis, displayed=basis.displayed.select(painted)),
        ), tuple(fragment for fragment in newest.prepared.fragments if fragment.evidence is page)

    @classmethod
    async def mark_read(cls, comms, target, project, page):
        from agent_comms.route_selection import implicit_root, run_selected_write

        assert page.display_basis is not None and page.newest_seq is not None
        await asyncio.to_thread(
            run_selected_write,
            comms.root,
            comms.views.mark_dm_view_read,
            target,
            worktree=project,
            through=page.newest_seq,
            expected_display_basis=page.display_basis,
            implicit=implicit_root(),
        )


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
