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
    def remember_tail(cls, view, page, older):
        pass

    @classmethod
    def remember_mounted(cls, view, page):
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
    def painted_page(cls, view, painted): ...

    @classmethod
    @abstractmethod
    async def mark_painted(cls, comms, target, project, page): ...


class ChannelConversation(ConversationKind):
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
    def remember_mounted(cls, view, page):
        view._channel_ack_pages.update((message.seq, page) for message in page.messages)

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
    def painted_page(cls, view, painted):
        mounted = {
            message.seq for message, _ in view._history if not message.view_key[0]
        }
        view._channel_ack_pages = {
            seq: source
            for seq, source in view._channel_ack_pages.items()
            if seq in mounted
        }
        original = next(
            (
                source
                for seq, source in view._channel_ack_pages.items()
                if seq in painted
            ),
            None,
        )
        if original is None:
            return None
        scope = original.display_scope
        if scope is None or scope.displayed is None:
            return None
        selected = {
            seq
            for seq, source in view._channel_ack_pages.items()
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
    def remember_tail(cls, view, page, older):
        if not older and page.messages and page.historical_display is None:
            view._ack_page = page

    @classmethod
    async def agent_info(cls, comms, target):
        return await asyncio.to_thread(comms.agents.agent_info_of, target)

    @classmethod
    def painted_page(cls, view, painted):
        original = view._ack_page
        if original is None or original.newest_seq not in painted:
            return None
        basis = original.display_basis
        if basis is None or basis.older_unread:
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
    def label(cls, target: str) -> str:
        return f"{target} · all comms"

    @classmethod
    def placeholder(cls, target):
        return "Message #all (broadcast)"

    @classmethod
    def send_target(cls, target):
        from toad.constants import ALL_COMMS_TARGET

        return ALL_COMMS_TARGET
