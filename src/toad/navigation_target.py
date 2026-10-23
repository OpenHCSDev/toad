"""One declared destination owner for row activation, menus and navigation."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from agent_comms.channel_targets import ChannelSelection, CommandTarget
from agent_comms.channel_targets import ChannelTarget as CoreChannelTarget
from agent_comms.channel_targets import ThreadTarget as CoreThreadTarget
from agent_comms.declared_family import DeclaredFamily

from toad.constants import ALL_COMMS_TARGET
from toad.navigation_context import NavigationContext, NavigationOwner
from toad.conversation_kind import (
    ChannelConversation,
    ConversationKind,
    DmConversation,
    IrcConversation,
)

if TYPE_CHECKING:
    from agent_comms.display_references import CurrentDisplayReferences

    from toad.widgets.comms_sidebar import CommsRow
    from toad.widgets.sidebar_tree import SidebarGroup

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

    def menu_context(self, sidebar, *, channel: ChannelSelection, mode_name=None):
        from toad.target_commands import TargetContext
        return TargetContext(sidebar.app, sidebar.model_state.observed.service, CommandTarget.named(self.name),
                             sidebar.app.workspace_sessions.source.view.navigation_context.actor,
                             sidebar.app.project_dir, mode_name, channel)

    def selected(self, owner: NavigationOwner) -> None:
        """Apply view-specific selection intent before beginning navigation."""

    def matches(self, target: NavigationTarget) -> bool:
        """Different opening behaviors may display the same sidebar address."""
        return self.name == target.name

    def rows_in(self, group: SidebarGroup[CommsRow]) -> tuple[CommsRow, ...]:
        return group.rows_for_target(self.name)

    @abstractmethod
    async def open(self, context: NavigationContext) -> str:
        pass


@dataclass(frozen=True)
class NoTarget(NavigationTarget):
    name: str = field(default="", init=False)

    def selected(self, owner: NavigationOwner) -> None:
        pass

    def matches(self, target: NavigationTarget) -> bool:
        return False

    def rows_in(self, group: SidebarGroup[CommsRow]) -> tuple[CommsRow, ...]:
        return ()

    async def open(self, context: NavigationContext) -> str:
        return context.owner_mode


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
    """A route declaration registers its conversation kind exactly once."""

    routes: ClassVar[dict[type[ConversationKind], type[HistoryRoute]]] = {}

    @classmethod
    @abstractmethod
    def for_name(cls, name: str) -> HistoryTarget: ...

class HistoryTarget(HistoryRoute, NavigationTarget):
    @classmethod
    def for_name(cls, name: str) -> HistoryTarget:
        return cls(name)

    @classmethod
    def for_conversation(cls, conversation: ConversationKind,
                         references: CurrentDisplayReferences) -> HistoryTarget:
        return HistoryRoute.routes[type(conversation)].for_name(conversation.destination(references).name)


class HistoryRouted(HistoryTarget, declared_name=None):
    """Routed destinations supply their kind; the intermediate is not a destination."""

    history_kind: ClassVar[type[ConversationKind]]

    def __init_subclass__(cls, **kwargs) -> None:
        if cls.history_kind in HistoryRoute.routes:
            raise TypeError(f"A history route already serves {cls.history_kind.__name__}")
        super().__init_subclass__(**kwargs)
        HistoryRoute.routes[cls.history_kind] = cls

    def prepare(self, comms, me):
        """Resolve opening intent before retaining a stable conversation key."""
        return self.history_kind.resolve(comms, me, self.name)

    async def open(self, context: NavigationContext) -> str:
        return await context.app.session_navigation.history(
            owner_mode=context.owner_mode, project_path=context.project_path,
            me=context.actor, route=self,
        )


class ChannelLike:
    """Shared channel-row capability; consumers never enumerate row kinds."""

    def menu_context(self, sidebar, **kwargs):
        from toad.target_commands import TargetContext
        return TargetContext(sidebar.app, sidebar.model_state.observed.service, CommandTarget.named(self.name),
                              sidebar.app.workspace_sessions.source.view.navigation_context.actor,
                              sidebar.app.project_dir)


@dataclass(frozen=True)
class FeedTarget(ChannelLike, HistoryRouted):
    name: str = field(default=ALL_COMMS_TARGET, init=False)
    history_kind = IrcConversation
    expanded_by_default = True

    @classmethod
    def for_name(cls, name: str):
        return cls()

class ChannelTarget(ChannelLike, HistoryRouted):
    history_kind = ChannelConversation


class DirectTarget(HistoryRouted):
    history_kind = DmConversation

    def selected(self, owner: NavigationOwner) -> None:
        owner.remember_direct_target(self.name)


def channel_target(name: str) -> NavigationTarget:
    """The aggregate name's canonical destination, chosen at row construction."""
    return FeedTarget() if name == ALL_COMMS_TARGET else ChannelTarget(name)
