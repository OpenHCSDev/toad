"""Typed navigation behavior; serialized target kinds are decoded only here."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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

    async def open_sidebar_target(self, name: str, kind: str) -> str:
        target = NavigationTarget.decode(name, kind)
        target.selected(self)
        return await target.open(self.navigation_context)


@dataclass(frozen=True)
class NavigationTarget(ABC):
    name: str

    @classmethod
    def decode(cls, name: str, kind: str) -> NavigationTarget:
        try:
            target_type = _TARGET_TYPES[kind]
        except KeyError:
            raise ValueError(f"Unknown navigation target kind: {kind!r}") from None
        return target_type.from_name(name)

    @classmethod
    def from_name(cls, name: str) -> NavigationTarget:
        return cls(name)

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
    async def open(self, context: NavigationContext) -> str:
        return await context.app.open_thread_session(
            owner_mode=context.owner_mode, project_path=context.project_path, target=self.name,
        )


class HistoryTarget(NavigationTarget):
    history_kind: ClassVar[type[ConversationKind]]

    async def open(self, context: NavigationContext) -> str:
        return await context.app._open_comms_history(
            owner_mode=context.owner_mode, project_path=context.project_path,
            me=context.actor, target=self.name, kind=self.history_kind,
        )


class FeedTarget(HistoryTarget):
    history_kind = IrcConversation

    @classmethod
    def from_name(cls, name: str) -> FeedTarget:
        return cls(ALL_COMMS_TARGET)


class ChannelTarget(HistoryTarget):
    history_kind = ChannelConversation

    @classmethod
    def from_name(cls, name: str) -> NavigationTarget:
        # The aggregate's declaration owns its route, rather than each view
        # repeating channel-name and kind comparisons.
        return _CHANNEL_TARGET_TYPES.get(name, cls)(name)


class DirectTarget(HistoryTarget):
    history_kind = DmConversation

    def selected(self, owner: NavigationOwner) -> None:
        owner.remember_direct_target(self.name)


_CHANNEL_TARGET_TYPES = {ALL_COMMS_TARGET: FeedTarget}
_TARGET_TYPES = {
    "session": SessionTarget,
    "thread": ThreadTarget,
    ChannelConversation.declared_name: ChannelTarget,
    IrcConversation.declared_name: FeedTarget,
    DmConversation.declared_name: DirectTarget,
}
