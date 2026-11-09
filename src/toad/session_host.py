"""The workspace and application capabilities used by logical session factories."""

from __future__ import annotations

from abc import abstractmethod
from typing import Self

from textual.abstract_hooks import AbstractHooksMeta
from textual.await_complete import AwaitComplete

from toad.comms_host import CommsHost
from toad.comms_root import CoordinationAccess, Observing
from toad.db import DB
from toad.navigation_context import NavigationOwner
from toad.navigation_preparation import NavigationReader
from toad.session_projection import SessionCollection, SessionProjection
from toad.session_scope import SessionOrigin, SessionScope
from toad.session_tracker import SessionTracker


class WorkspaceViews(metaclass=AbstractHooksMeta):
    """The workspace owns native views and their dependent lifetime."""

    views: dict[str, SessionScope]

    @abstractmethod
    def require(self, identity: str) -> SessionScope: ...

    @abstractmethod
    def origin(self, identity: str) -> SessionOrigin: ...

    @abstractmethod
    def navigation_owner(self) -> NavigationOwner: ...

    @abstractmethod
    def detach(self, identity: str) -> SessionScope | None: ...

    @abstractmethod
    async def finish(self, view: SessionScope) -> None: ...


class NavigationHost(CommsHost[Observing]):
    """A native application selects sessions through its workspace and tab owners."""

    workspace_sessions: WorkspaceViews
    coordination_access: CoordinationAccess
    session_navigation: SessionNavigator
    session_tracker: SessionTracker
    navigation_reader: NavigationReader
    selected_mode: str

    @abstractmethod
    async def get_db(self) -> DB: ...

    @abstractmethod
    def select_session(self, mode: str) -> AwaitComplete: ...

    @abstractmethod
    def update_show_sessions(self) -> None: ...


class SessionNavigator(SessionCollection[Observing]):
    """The session factory's context supplies its application and current membership."""

    app: NavigationHost

    @abstractmethod
    def get(self, mode: str | None) -> SessionProjection[Self, Observing] | None: ...
