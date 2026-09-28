"""One declared destination owner for row activation, menus and navigation."""

from __future__ import annotations

from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from toad.conversation_kind import ConversationKind, ChannelConversation, DmConversation, IrcConversation
from toad.constants import ALL_COMMS_TARGET

if TYPE_CHECKING:
    from toad.app import ToadApp


@dataclass(frozen=True)
class NavigationContext:
    app: ToadApp
    owner_mode: str
    project_path: Path
    actor: str


class NavigationOwner:
    """Views supply context, targets supply behavior, App owns execution."""

    @property
    def navigation_context(self) -> NavigationContext:
        raise NotImplementedError

    def remember_direct_target(self, target: str) -> None:
        """Optional view-local return-to-DM intent."""

    async def open_sidebar_target(self, target: NavigationTarget) -> str:
        target.selected(self)
        return await target.open(self.navigation_context)


@dataclass(frozen=True)
class NavigationTarget(DeclaredFamily, affix="Target"):
    name: str

    expanded_by_default: ClassVar[bool] = False

    def show_menu(self, sidebar, offset, *, mode_name=None, channel=None) -> None:
        sidebar._show_thread_menu(self.name, offset, mode_name=mode_name, channel=channel)

    def toggle_members(self, sidebar, channel: str) -> bool:
        return False

    def unread(self, snapshot):
        from toad.session_tracker import ExactUnread
        return ExactUnread(snapshot.unread.get(self.name, 0))

    def selected(self, owner: NavigationOwner) -> None:
        """Apply view-specific selection intent before beginning navigation."""

    @abstractmethod
    async def open(self, context: NavigationContext) -> str:
        pass


class SessionTarget(NavigationTarget):
    async def open(self, context: NavigationContext) -> str:
        app = context.app
        destination = context.owner_mode if app.session_tracker.get_session(context.owner_mode) else "store"
        if app.current_mode != destination:
            await app.switch_mode(destination)
        return app.current_mode


class ThreadTarget(NavigationTarget):
    def unread(self, snapshot):
        from toad.session_tracker import UnreadPresentation
        return UnreadPresentation.for_thread(snapshot, self.name)

    async def open(self, context: NavigationContext) -> str:
        return await context.app.open_thread_session(
            owner_mode=context.owner_mode, project_path=context.project_path, target=self.name,
        )


class HistoryTarget(NavigationTarget):
    @property
    @abstractmethod
    def history_kind(self) -> type[ConversationKind]: ...

    async def open(self, context: NavigationContext) -> str:
        return await context.app._open_comms_history(
            owner_mode=context.owner_mode, project_path=context.project_path,
            me=context.actor, target=self.name, kind=self.history_kind,
        )


class ChannelLike:
    """Shared channel-row capability; consumers never enumerate row kinds."""

    def show_menu(self, sidebar, offset, **kwargs) -> None:
        sidebar._show_channel_menu(self.name, offset)

    def toggle_members(self, sidebar, channel: str) -> bool:
        sidebar._virtual_toggle(channel)
        return True


@dataclass(frozen=True)
class FeedTarget(ChannelLike, HistoryTarget):
    name: str = field(default=ALL_COMMS_TARGET, init=False)
    history_kind = IrcConversation
    expanded_by_default = True


class ChannelTarget(ChannelLike, HistoryTarget):
    history_kind = ChannelConversation


class DirectTarget(HistoryTarget):
    history_kind = DmConversation

    def selected(self, owner: NavigationOwner) -> None:
        owner.remember_direct_target(self.name)


def channel_target(name: str) -> NavigationTarget:
    """The aggregate name's canonical destination, chosen at row construction."""
    return FeedTarget() if name == ALL_COMMS_TARGET else ChannelTarget(name)


def linked_target(name: str) -> NavigationTarget:
    """Decode a clicked wire identity at the link boundary."""
    return channel_target(name) if name.startswith("#") else ThreadTarget(name)


def person_target(person) -> NavigationTarget:
    """A runnable native owner opens a session; stopped peers open retained DMs."""
    name = person.thread.name
    if person.status.active and (person.thread.session_file or person.thread.pid > 0):
        return ThreadTarget(name)
    return DirectTarget(name)
