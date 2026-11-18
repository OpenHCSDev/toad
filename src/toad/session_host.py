"""The workspace and application capabilities used by logical session factories."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Self

from formbridge.forms.declared_fields import DeclaredViews
from metaclass_registry import AbstractHooksMeta

from toad.client.host import NavigatingHost
from toad.client.connection import CoordinationAccess, Observing
from toad.client.db import DB
from toad.navigation_context import NavigationOwner
from toad.navigation_preparation import NavigationReader
from toad.client.session_projection import SessionCollection, SessionProjection
from toad.client.session_scope import SessionOrigin, SessionScope
from toad.client.session_tracker import SessionTracker
from toad.client.tab_identity import TabIdentity, TabNotDrawnHere

if TYPE_CHECKING:
    from toad.navigation_preparation import ThreadNavigationRequest
    from toad.thread_navigation import ThreadOrigin
    from toad.client.tab_identity import SessionTabIdentity


class SessionEntries(DeclaredViews):
    """A frontend's session entries, each building the view of the tab identities it shows.

    A native application declares its frontend's root as `session_entries`; navigation asks
    that root for an identity's member, so shared code never names a frontend's classes.
    """

    @classmethod
    def declared_for(cls, identity: TabIdentity) -> Callable[..., Self]:
        try:
            return cls.showing(identity.declarations())
        except LookupError as missing:
            raise TabNotDrawnHere(identity) from missing


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


class NavigationHost(NavigatingHost[Observing]):
    """A native application selects sessions through its workspace and tab owners."""

    workspace_sessions: WorkspaceViews
    coordination_access: CoordinationAccess
    session_navigation: SessionNavigator
    session_tracker: SessionTracker
    navigation_reader: NavigationReader
    selected_mode: str
    session_entries: type[SessionEntries]

    @abstractmethod
    async def get_db(self) -> DB: ...

    @abstractmethod
    def select_session(self, mode: str) -> Awaitable[object]: ...

    @abstractmethod
    def update_show_sessions(self) -> None: ...

    @abstractmethod
    def make_opening_view(
        self,
        request: ThreadNavigationRequest,
        origin: ThreadOrigin,
        identity: SessionTabIdentity,
    ) -> SessionScope:
        """The loading placeholder a thread-navigation opening mounts while its async
        read resolves, then rebinds with the real content. Textual returns
        `MainScreen.opening(...)`; Qt returns a `QtOpeningSessionView`. Each frontend
        owns its placeholder so this shared layer (and `ThreadOpening`) does not have to
        import the Textual-widget pyramid just to reach `MainScreen`."""
        ...

    @abstractmethod
    def thread_view(self, prepared) -> SessionScope:
        """The view of a thread a named launch opens without an opening placeholder (a
        restored tab, a resumed session), bound to the thread's incarnation under its root.
        Textual draws a `MainScreen`; Qt the `QtMailboxView` its sidebar opens."""

    @abstractmethod
    def replace_opening_view(
        self,
        opening_view: SessionScope,
        prepared,
        identity: SessionTabIdentity,
    ) -> SessionScope:
        """The real bound view the opening placeholder becomes once
        `ThreadNavigation` has resolved. Called by `ThreadNavigator.mount` BEFORE
        `prepared.bind(view)` + `session_navigation.bind_opened(view, ...)` +
        `view._prepare_content()`, so each runs against the bound-state view
        (which has the full SessionScope / Qt-page surface) rather than against
        the opening placeholder (which was deliberately kept minimal).

        Textual returns `opening_view` unchanged — `MainScreen` is one class for
        both the opening and bound lifecycle phases, same instance updated
        in-place. Qt constructs a fresh `QtMailboxView`, swaps it into
        `QtWorkspaceViews.pages` + `.views` at the opening view's mode slot,
        and returns the new instance so the rest of `mount` drives it. This is
        the Qt analogue of Textual's "one widget handles both phases"."""
        ...


class SessionNavigator(SessionCollection[Observing]):
    """The session factory's context supplies its application and current membership."""

    app: NavigationHost

    @abstractmethod
    def get(self, mode: str | None) -> SessionProjection[Self, Observing] | None: ...
