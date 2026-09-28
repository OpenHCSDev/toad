"""One declared conversation family owns history reads and route preparation."""

from __future__ import annotations

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
            return ("historical", displayed.viewer, displayed.viewer_created_at, page.history_revision)
        return cls.current_identity(page)

    @classmethod
    @abstractmethod
    def current_identity(cls, page: MessagePage) -> tuple | None: ...

    @classmethod
    def label(cls, target: str) -> str:
        return target


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
            displayed.viewer, displayed.viewer_created_at, displayed.bus_identity,
            scope.channel, scope.targets, scope.any_mode,
            scope.participant_names if scope.any_mode else frozenset(), page.history_revision,
        )


class DmConversation(ConversationKind):
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
            basis.root_identity, basis.bus_identity, basis.worktree, basis.requested_peer,
            basis.viewer, basis.viewer_created_at, basis.viewer_names,
            basis.peer, basis.peer_created_at, basis.peer_names, page.history_revision,
        )

    @classmethod
    def label(cls, target: str) -> str:
        return f"@{target}"


class IrcConversation(ChannelConversation):
    @classmethod
    def label(cls, target: str) -> str:
        return f"{target} · all comms"
