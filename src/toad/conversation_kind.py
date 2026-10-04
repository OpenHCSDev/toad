"""One declared conversation family owns history reads and route preparation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from agent_comms.comms import Comms
from agent_comms.message_page import MessagePage


class ConversationKind(DeclaredFamily, affix="Conversation"):
    @classmethod
    def admitted_threads(cls, snapshot, me, target):
        return ()

    @classmethod
    def admitted_channels(cls, root, target):
        return ()

    @classmethod
    def view_identity(cls, key):
        return key

    @classmethod
    @abstractmethod
    def page(cls, comms: Comms, target: str, **bounds) -> MessagePage: ...

    @classmethod
    @abstractmethod
    def resolve(cls, comms: Comms, me: str, target: str) -> tuple[str, str]: ...

    @classmethod
    def display_identity(cls, page: MessagePage) -> tuple | None:
        if page.historical_display is not None:
            displayed = page.historical_display.displayed
            return (
                "historical",
                displayed.viewer,
                displayed.viewer_created_at,
                page.history_revision,
            )
        return cls.current_identity(page)

    @classmethod
    @abstractmethod
    def current_identity(cls, page: MessagePage) -> tuple | None: ...

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
        from toad.navigation_target import DirectTarget
        from toad.widgets.comms_sidebar import CommsSidebar

        sidebar = screen.query_one(CommsSidebar)
        peers = [name for name in sorted(sidebar.observation.registry_names())
                 if name != screen.me]
        if peers:
            await screen.open_sidebar_target(DirectTarget(peers[0]))

    @classmethod
    def unread(cls, snapshot, target):
        from toad.session_tracker import ExactUnread
        return ExactUnread(snapshot.channel_unread.get(target, 0)) if snapshot else ExactUnread()

    @classmethod
    def placeholder(cls, target):
        return f"Message {target}"

    @classmethod
    def send_target(cls, target):
        return target

    @classmethod
    def remember_page(cls, history, page, older):
        """Only committed mounted pages supply read-receipt authority."""
        mounted = {message.view_key for message, _ in history.rows}
        history.historical_receipts = {
            key: source for key, source in history.historical_receipts.items() if key in mounted
        }
        cls.remember_tail(history, page, older, mounted)
        cls.remember_mounted(history, page, mounted)
        if page is not None and page.historical_display is not None:
            history.historical_receipts.update(
                (message.view_key, page) for message in page.messages if message.view_key in mounted
            )

    @classmethod
    def remember_tail(cls, history, page, older, mounted):
        pass

    @classmethod
    def remember_mounted(cls, history, page, mounted):
        pass

    @classmethod
    def read_only(cls, catalog, target):
        return False

    @classmethod
    async def update_roster(cls, view, comms):
        pass

    @classmethod
    async def agent_info(cls, comms, target):
        return None

    @classmethod
    @abstractmethod
    def activity_widget(cls, view): ...

    @classmethod
    @abstractmethod
    def prompt(cls, target): ...

    @classmethod
    @abstractmethod
    def painted_page(cls, history, painted): ...

    @classmethod
    @abstractmethod
    async def mark_painted(cls, comms, target, project, page): ...


class ChannelConversation(ConversationKind):
    @classmethod
    def admitted_channels(cls, root, target):
        return ((root, target),)

    @classmethod
    def view_identity(cls, key):
        from toad.session_tracker import ChannelViewAddress
        return ChannelViewAddress(key.root, key.target, cls)

    @classmethod
    def page(cls, comms: Comms, target: str, **bounds) -> MessagePage:
        return comms.views.channel_display_page(target, **bounds)

    @classmethod
    def resolve(cls, comms: Comms, me: str, target: str) -> tuple[str, str]:
        if me in comms.registry:
            me = comms.registry.require(me).name
        return me, comms.channels.catalog.read().resolve(target).name

    @classmethod
    def current_identity(cls, page: MessagePage) -> tuple | None:
        scope = page.display_scope
        if scope is None or scope.displayed is None:
            return None
        displayed = scope.displayed
        return (
            displayed.viewer,
            displayed.viewer_created_at,
            displayed.bus_identity,
            scope.channel,
            scope.targets,
            scope.any_mode,
            scope.participant_names if scope.any_mode else frozenset(),
            page.history_revision,
        )

    @classmethod
    def activity_widget(cls, view):
        from toad.widgets.channel_participants import ChannelParticipants

        return ChannelParticipants()

    @classmethod
    def prompt(cls, target):
        from toad.widgets.channel_prompt import ChannelPrompt

        return ChannelPrompt(simple_input=True, placeholder=cls.placeholder(target))

    @classmethod
    def remember_mounted(cls, history, page, mounted):
        history.channel_receipts = {
            seq: source for seq, source in history.channel_receipts.items() if ("", seq) in mounted
        }
        if page is not None and cls.current_identity(page) is not None:
            history.channel_receipts.update(
                (message.seq, page) for message in page.messages if message.view_key in mounted
            )

    @classmethod
    def read_only(cls, catalog, target):
        return catalog.is_view_target(target)

    @classmethod
    async def update_roster(cls, view, comms):
        from toad.widgets.channel_participants import ChannelParticipants
        from toad.widgets.channel_prompt import ChannelPrompt

        snapshot = await asyncio.to_thread(comms.views.coordination_snapshot)
        view.query_one(ChannelParticipants).update_participants(
            snapshot.participants(view.target)
        )
        view.query_one(ChannelPrompt).set_mention_candidates(
            snapshot.mention_candidates(view.target)
        )

    @classmethod
    def painted_page(cls, history, painted):
        original = next(
            (
                source
                for seq, source in history.channel_receipts.items()
                if seq in painted
            ),
            None,
        )
        if original is None:
            return None
        scope = original.display_scope
        selected = {
            seq
            for seq, source in history.channel_receipts.items()
            if source is original and seq in painted
        }
        return replace(
            original,
            messages=tuple(
                message for message in original.messages if message.seq in selected
            ),
            display_scope=replace(scope, displayed=scope.displayed.select(selected)),
        ), original

    @classmethod
    async def mark_painted(cls, comms, target, project, page):
        from toad.comms_root import implicit_root, run_selected_write

        assert page.display_scope is not None and page.newest_seq is not None
        await asyncio.to_thread(
            run_selected_write,
            comms.root,
            comms.views.mark_channel_view_read,
            target,
            worktree=project,
            through=page.newest_seq,
            expected_scope=page.display_scope,
            implicit=implicit_root(),
        )


class DmConversation(ConversationKind):
    @classmethod
    def historical_thread(cls, target: str) -> str:
        return target

    @classmethod
    async def toggle_dm(cls, screen) -> None:
        await screen.action_back_to_agent()

    @classmethod
    def admitted_threads(cls, snapshot, me, target):
        return (snapshot.require(me).incarnation, snapshot.require(target).incarnation)

    @classmethod
    def unread(cls, snapshot, target):
        from toad.session_tracker import ExactUnread
        return ExactUnread(snapshot.unread.get(target, 0)) if snapshot else ExactUnread()

    @classmethod
    def page(cls, comms: Comms, target: str, **bounds) -> MessagePage:
        return comms.views.dm_display_page(target, **bounds)

    @classmethod
    def resolve(cls, comms: Comms, me: str, target: str) -> tuple[str, str]:
        return comms.registry.require(me).name, comms.registry.require(target).name

    @classmethod
    def current_identity(cls, page: MessagePage) -> tuple | None:
        basis = page.display_basis
        if basis is None:
            return None
        return (
            basis.root_identity,
            basis.bus_identity,
            basis.worktree,
            basis.requested_peer,
            basis.viewer,
            basis.viewer_created_at,
            basis.viewer_names,
            basis.peer,
            basis.peer_created_at,
            basis.peer_names,
            page.history_revision,
        )

    @classmethod
    def label(cls, target: str) -> str:
        return f"@{target}"

    @classmethod
    def activity_widget(cls, view):
        from toad.widgets.session_details import SessionDetails

        return SessionDetails(view._read_thread_activity)

    @classmethod
    def prompt(cls, target):
        from toad.widgets.prompt import Prompt

        return Prompt(simple_input=True, placeholder=cls.placeholder(target))

    @classmethod
    def remember_tail(cls, history, page, older, mounted):
        original = history.tail_receipt
        if original is not None and ("", original.newest_seq) not in mounted:
            history.tail_receipt = None
        if page is not None and not older and cls.current_identity(page) is not None:
            history.tail_receipt = page if page.messages else None

    @classmethod
    async def agent_info(cls, comms, target):
        return await asyncio.to_thread(comms.agents.agent_info_of, target)

    @classmethod
    def painted_page(cls, history, painted):
        original = history.tail_receipt
        if original is None or original.newest_seq not in painted:
            return None
        basis = original.display_basis
        if basis.older_unread:
            return None
        inbound = (
            message.seq
            for message in original.messages
            if message.sender in basis.peer_names
            and message.target in basis.viewer_names
        )
        if any(sequence not in painted for sequence in inbound):
            return None
        return replace(
            original,
            messages=tuple(
                message for message in original.messages if message.seq in painted
            ),
            display_basis=replace(basis, displayed=basis.displayed.select(painted)),
        ), original

    @classmethod
    async def mark_painted(cls, comms, target, project, page):
        from toad.comms_root import implicit_root, run_selected_write

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
