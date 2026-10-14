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
        from toad.navigation_target import DirectTarget
        peers = [name for name in sorted(await screen.app.registry_names())
                 if name != screen.me]
        if peers:
            await screen.open_sidebar_target(DirectTarget(peers[0]))

    @classmethod
    def unread(cls, snapshot, target):
        from agent_comms.ui_model.unread import ExactUnread
        return ExactUnread(snapshot.channel_unread.get(target, 0)) if snapshot else ExactUnread()

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
    def activity_widget(cls, view):
        from toad.widgets.channel_participants import ChannelParticipants

        return ChannelParticipants()

    @classmethod
    def prompt(cls, target):
        from toad.widgets.channel_prompt import ChannelPrompt

        return ChannelPrompt(simple_input=True, placeholder=cls.placeholder(target))

    @classmethod
    def read_only(cls, catalog, target):
        return catalog.is_view_target(target)

    @classmethod
    async def update_roster(cls, view, comms):
        from toad.widgets.channel_participants import ChannelParticipants
        from toad.widgets.channel_prompt import ChannelPrompt

        # The composer consumes membership and thread presentation, not the
        # actor's inbox counts or channel activity clocks. Borrow the observed
        # service's sidebar model rather than reading the same registry,
        # activity and catalog again after every channel page.
        history = view.message_history
        source = history.source_snapshot()
        target = view.target
        access = view.app.coordination_access
        await access.current_sidebar()
        observed = access.observation
        if observed is None or observed.service is not comms:
            raise ValueError("Channel roster belongs to another Comms service")
        snapshot, rows = observed.sidebar.snapshot, observed.sidebar.threads.rows
        if snapshot is None:
            raise ValueError("Sidebar read was interrupted; the next page retries")

        def prepare():
            people = tuple(rows[person.thread.name] for person in snapshot.participants(target)
                           if person.thread.name in rows)
            return (ChannelParticipants.prepare_participants(people),
                    snapshot.mention_candidates(target))

        participants, mentions = await view.app.preparation.run_thread(prepare)
        if not await history.source_is_current(source) or view.target != target:
            return
        view.query_one(ChannelParticipants).update_participants(*participants)
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
        from agent_comms.ui_model.unread import ExactUnread
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

        return SessionDetails()

    @classmethod
    def prompt(cls, target):
        from toad.widgets.prompt import Prompt

        return Prompt(simple_input=True, placeholder=cls.placeholder(target))

    @classmethod
    async def agent_info(cls, comms, target):
        def read_info():
            thread = comms.registry.require(target)
            info = comms.agents.agent_info_of(thread.name)
            if info is not None:
                return replace(info, model=thread.model)
            if thread.model is not None:
                from agent_comms.runtime_info import AgentRuntimeInfo

                return AgentRuntimeInfo(thread=thread.name, timestamp=0.0, model=thread.model)
            return None

        return await asyncio.to_thread(read_info)

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
