"""One declared destination owner for row activation, menus and navigation."""

from __future__ import annotations

from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from agent_comms.thread_execution import ConversationPreparation
from agent_comms.presentation import ThreadView
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

    def menu_context(self, sidebar, *, mode_name=None, channel=None):
        from toad.target_commands import TargetContext
        return TargetContext(sidebar.app, sidebar.observation.service, self.name,
                             sidebar.session_thread, sidebar.app.project_dir, mode_name, channel)

    def show_menu(self, sidebar, offset, **kwargs) -> None:
        self.menu_context(sidebar, **kwargs).show_menu(sidebar, offset)

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
        if app.selected_mode != destination:
            await app.select_session(destination)
        return app.selected_mode


class NativeUnread:
    """Unread identity for destinations backed by a native owner journal."""

    def unread(self, snapshot):
        from toad.session_tracker import UnreadPresentation
        return UnreadPresentation.for_thread(snapshot, self.name)

class ThreadTarget(NativeUnread, NavigationTarget):
    async def open(self, context: NavigationContext) -> str:
        return await context.app.thread_navigation.open(
            owner_mode=context.owner_mode, project_path=context.project_path, target=self.name,
        )


class HistoryRoute:
    """Conversation families declare the history source used for navigation."""

    @property
    @abstractmethod
    def history_kind(self) -> type[ConversationKind]: ...

class HistoryTarget(HistoryRoute, NavigationTarget):
    async def open(self, context: NavigationContext) -> str:
        return await context.app.session_navigation.history(
            owner_mode=context.owner_mode, project_path=context.project_path,
            me=context.actor, target=self.name, kind=self.history_kind,
        )


class ChannelLike:
    """Shared channel-row capability; consumers never enumerate row kinds."""

    def menu_context(self, sidebar, **kwargs):
        from toad.target_commands import TargetContext
        return TargetContext(sidebar.app, sidebar.observation.service, self.name,
                              sidebar.session_thread, sidebar.app.project_dir)


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
    """The original receiving declaration selects session or canonical bus history."""
    return person.thread.execution.prepare_conversation(PersonConversationPreparation(person))


@dataclass(frozen=True)
class PersonConversationPreparation(ConversationPreparation):
    person: ThreadView

    def external(self) -> NavigationTarget:
        return DirectTarget(self.person.thread.name)

    def native(self) -> NavigationTarget:
        name = self.person.thread.name
        return ThreadTarget(name) if self.person.status.active else DirectTarget(name)
