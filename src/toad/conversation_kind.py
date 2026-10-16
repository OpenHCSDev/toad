"""One declared conversation family owns history reads and route preparation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from agent_comms.comms import Comms
from agent_comms.message_page import MessagePage
from toad.widgets.session_details import SessionDetails


class ConversationKind(DeclaredFamily, affix="Conversation"):
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
        await screen.action_back_to_agent()
        screen.app.session_navigation.direct_messages()

    @classmethod
    def unread(cls, snapshot, target):
        from agent_comms.ui_model.unread import UnreadPresentation
        return UnreadPresentation.for_channel(snapshot, target)

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
    @abstractmethod
    def activity_widgets(cls) -> tuple[type[SessionDetails], ...]:
        """Declare widget classes; the composing view owns their instances."""
        ...

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
    @classmethod
    def channels_needed(cls, root, target):
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
    def activity_widgets(cls) -> tuple[type[SessionDetails], ...]:
        return ()

    @classmethod
    async def status_text(cls, comms, target, *, read_only: bool) -> str:
        return "Read-only saved view" if read_only else ""

    @classmethod
    def prompt(cls, target):
        from toad.widgets.channel_prompt import ChannelPrompt

        return ChannelPrompt(simple_input=True, placeholder=cls.placeholder(target))

    @classmethod
    def read_only(cls, catalog, target):
        return catalog.is_view_target(target)

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
        if observed is None or observed.service is not comms:
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
    def threads_needed(cls, snapshot, me, target):
        return (snapshot.require(me).incarnation, snapshot.require(target).incarnation)

    @classmethod
    def unread(cls, snapshot, target):
        from agent_comms.ui_model.unread import UnreadPresentation
        return UnreadPresentation.for_bus(snapshot, target)

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
    def activity_widgets(cls) -> tuple[type[SessionDetails], ...]:
        return (SessionDetails,)

    @classmethod
    async def update_mentions(cls, view, comms) -> None:
        """Direct-message composers have no channel mention roster."""

    @classmethod
    def prompt(cls, target):
        from toad.widgets.prompt import Prompt

        return Prompt(simple_input=True, placeholder=cls.placeholder(target))

    @classmethod
    async def status_text(cls, comms, target, *, read_only: bool) -> str:
        info = await asyncio.to_thread(comms.configuration.answer, target)
        return " · ".join(
            value for value in (
                info.model or "",
                info.context_usage.label if info.context_usage is not None else "",
            ) if value
        )

    @classmethod
    def seen_page(cls, history, seen):
        # Only the newest page marks a direct conversation read, and only as a
        # whole: its newest message and every message from the peer were seen.
        newest = history.pages[-1]
        page = newest.page.source
        if history.has_newer or page is None:
            return None
        painted = {fragment.message.seq for fragment in seen if fragment.evidence is page}
        if page.newest_seq not in painted:
            return None
        basis = page.display_basis
        if basis.older_unread:
            return None
        if any(message.seq not in painted for message in page.messages
               if message.sender in basis.peer_names and message.target in basis.viewer_names):
            return None
        return replace(
            page,
            messages=tuple(message for message in page.messages if message.seq in painted),
            display_basis=replace(basis, displayed=basis.displayed.select(painted)),
        ), tuple(fragment for fragment in newest.fragments if fragment.evidence is page)

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
