"""Shared session entry identity and projection — no native screen creation.

Native entries (Textual, Qt) inherit this and add source/view factories.
"""

from __future__ import annotations

from abc import abstractmethod

from agent_comms.ui_model.sidebar import ThreadRowModel

from toad.client.connection import Observing
from toad.client.session_projection import SessionProjection
from toad.client.session_scope import SessionScope
from toad.client.tab_identity import TabIdentity

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.registry.thread_identity import ThreadIncarnation


class SessionNavigator:
    """The navigation contract shared entries need. Native implementations
    provide the full session navigation with view management."""
    pass


class SharedSessionEntry(DeclaredFamily, SessionProjection[SessionNavigator, Observing], affix="Entry"):
    """Logical session identity, ownership and dependencies.

    Native entries add screen/view factories through DeclaredViews.
    """

    def __init__(self, identity: TabIdentity) -> None:
        self.identity = identity

    @property
    def mode(self) -> str:
        return self.identity.mode_name

    @property
    def owner_mode(self) -> str:
        return self.mode

    @abstractmethod
    def __call__(self) -> SessionScope: ...

    @property
    @abstractmethod
    def address(self) -> object: ...

    async def ready(self, sessions: SessionNavigator) -> None:
        """Views with deferred loading own their loading completion."""

    async def reconnect(self, sessions: SessionNavigator, selected, snapshot, targets) -> None:
        """Only a bound native entry can refresh its connection resource."""

    def source(self, sessions: SessionNavigator) -> object | None:
        return None

    def thread_row(self, sessions: SessionNavigator, row: ThreadRowModel) -> ThreadRowModel:
        return row

    def depends_on(self, mode: str) -> bool:
        return self.mode == mode

    def original_channels(self) -> tuple[tuple[str, str], ...]:
        return ()

    def original_threads(self, sessions: SessionNavigator) -> tuple[tuple[str, ThreadIncarnation], ...]:
        return ()

    def return_to(self, sessions: SessionNavigator) -> None:
        raise NotImplementedError

    def forget(self, sessions: SessionNavigator) -> None:
        raise NotImplementedError
