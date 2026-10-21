"""One declared destination owner for row activation, menus and navigation."""

from __future__ import annotations

from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily
from agent_comms.channel_targets import CommandTarget, ChannelTarget as CoreChannelTarget, ThreadTarget as CoreThreadTarget
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from toad.conversation_kind import ConversationKind, ChannelConversation, DmConversation, IrcConversation
from toad.constants import ALL_COMMS_TARGET

if TYPE_CHECKING:
    from toad.navigation_context import NavigationContext, NavigationOwner


@dataclass(frozen=True)
class NavigationTarget(DeclaredFamily, affix="Target"):
    name: str

    expanded_by_default: ClassVar[bool] = False

    @classmethod
    def named(cls, name: str) -> NavigationTarget:
        """Adapt Core's decoded wire identity to its frontend destination."""
        match CommandTarget.named(name):
            case CoreChannelTarget(name=name):
                return channel_target(name)
            case CoreThreadTarget(name=name):
                return ThreadTarget(name)
        raise TypeError("Expected a named channel or thread target")

    def menu_context(self, sidebar, *, mode_name=None, channel=None):
        from toad.target_commands import TargetContext
        return TargetContext(sidebar.app, sidebar.model_state.observed.service, self.name,
                             sidebar.app.workspace_sessions.source.view.navigation_context.actor,
                             sidebar.app.project_dir, mode_name, channel)

    def show_menu(self, sidebar, offset, **kwargs) -> None:
        self.menu_context(sidebar, **kwargs).show_menu(sidebar, offset)

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


class ThreadTarget(NavigationTarget):
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
            me=context.actor, conversation=self.history_kind(CommandTarget.named(self.name)),
        )


class ChannelLike:
    """Shared channel-row capability; consumers never enumerate row kinds."""

    def menu_context(self, sidebar, **kwargs):
        from toad.target_commands import TargetContext
        return TargetContext(sidebar.app, sidebar.model_state.observed.service, self.name,
                              sidebar.app.workspace_sessions.source.view.navigation_context.actor,
                              sidebar.app.project_dir)


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
