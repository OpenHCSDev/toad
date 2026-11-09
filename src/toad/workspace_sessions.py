"""Logical session membership; Textual owns only the persistent native frame."""

from toad.screens.welcome import WelcomeScreen
from toad.screens.workspace import SessionHost, WorkspaceScreen
from abc import abstractmethod
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path

from agent_comms.nominal.declared_family import DeclaredFamily
from textual._time import after_input

from toad.constants import WELCOME
from toad.navigation_context import NavigationOwner, NoNavigationOwner
from toad.navigation_target import NavigationTarget, NoTarget
from toad.session_scope import (
    NoSessionOrigin,
    SessionOrigin,
    SessionScope,
)
from toad.session_navigation import SessionNavigation
from toad.widget_actions import DeclaredWidgetActions
from toad.widgets.side_bar import SideBar
from toad.workspace_chrome import WorkspaceChrome


def welcome_view() -> SessionScope:
    return WelcomeScreen()


class WorkspaceSource(DeclaredFamily, affix="WorkspaceSource"):
    """Owns the selected view, including closing it outside the workspace."""

    @abstractmethod
    def matches(self, view: SessionScope) -> bool: ...

    def current(self, view: SessionScope) -> bool:
        return False

    def shown(self, view: SessionScope) -> bool:
        return False

    def keyboard_scopes(self) -> tuple[DeclaredWidgetActions, ...]:
        """A detached source contributes no session keyboard controls."""
        return ()

    @abstractmethod
    async def retire(self) -> WorkspaceSource: ...

    @abstractmethod
    def hide(self) -> None: ...

    @abstractmethod
    def commands(self) -> set: ...

    @abstractmethod
    def coordination_root(self): ...

    @abstractmethod
    def focus_sidebar_return(self) -> None: ...

    def publication(self, sessions: WorkspaceSessions) -> VisiblePublication:
        return VisiblePublication(None)

    @abstractmethod
    def navigation_owner(self, sessions: WorkspaceSessions) -> NavigationOwner:
        """The view the shared channels sidebar and DM entry points open through."""

    @abstractmethod
    def sidebars(self) -> tuple[SideBar, ...]:
        """Native sidebar membership belongs to this logical source."""
        ...


class DetachedWorkspaceSource(WorkspaceSource):
    view = None
    identity = "workspace"

    def matches(self, view):
        return False

    async def retire(self):
        return self

    def hide(self) -> None:
        pass

    def commands(self):
        return set()

    def coordination_root(self):
        return None

    def focus_sidebar_return(self) -> None:
        """A detached workspace has no return target."""

    def navigation_owner(self, sessions: WorkspaceSessions) -> NavigationOwner:
        return NoNavigationOwner(sessions.app)

    def sidebars(self) -> tuple[SideBar, ...]:
        return ()


class BoundWorkspaceSource(WorkspaceSource):
    def __init__(self, view: SessionScope) -> None:
        self.view = view

    @abstractmethod
    def current(self, view: SessionScope) -> bool: ...

    @property
    def identity(self):
        return self.view.id

    def matches(self, view):
        return self.view is view

    def navigation_owner(self, sessions: WorkspaceSessions) -> NavigationOwner:
        return self.view.navigation_owner

    async def retire(self):
        # Source retirement captures the departing reader from its committed
        # scene. Blurring or hiding first changes the widget's CSS state and
        # discards the document's source placement before its owner can take it.
        await self.view.retire_presentation()
        return ParkedWorkspaceSource(self.view)

    def hide(self) -> None:
        self.view.display = False

    def commands(self):
        return self.view.COMMANDS

    def coordination_root(self):
        return self.view.coordination_root

    def focus_sidebar_return(self) -> None:
        self.view.focus_sidebar_return()

    def publication(self, sessions: WorkspaceSessions) -> VisiblePublication:
        return VisiblePublication(
            sessions.views.get(self.identity) if sessions.owns(self.view) else None)

    def sidebars(self) -> tuple[SideBar, ...]:
        return self.view.sidebars()

    def keyboard_scopes(self) -> tuple[DeclaredWidgetActions, ...]:
        return self.view.keyboard_scopes()


class LoadingWorkspaceSource(BoundWorkspaceSource):
    def current(self, view):
        return self.matches(view)


class ShownWorkspaceSource(BoundWorkspaceSource):
    def current(self, view):
        return self.matches(view)

    def shown(self, view):
        return self.matches(view)


class ParkedWorkspaceSource(BoundWorkspaceSource):
    def current(self, view):
        return False

    async def retire(self):
        return self


class SessionStartFailed(RuntimeError):
    """A session's own startup failed; the app has already shown that error."""


@dataclass(frozen=True)
class VisiblePublication:
    """The selected view, published when the source changes. The view owns its target and its
    root applicability; the target is derived live from it on read, never cached."""

    view: SessionScope | None

    def target_for(self, root: Path | None) -> NavigationTarget:
        return (
            self.view.navigation_target
            if root is not None and self.view is not None and self.view.belongs_to_wire(root)
            else NoTarget()
        )


class WorkspaceHost:
    """What workspace sessions work through. The app inherits this and provides each member;
    declaring it here means this module never imports the app."""

    workspace_screen: WorkspaceScreen
    workspace_chrome: WorkspaceChrome
    session_navigation: SessionNavigation


class WorkspaceSessions:
    def __init__(self, app: WorkspaceHost) -> None:
        self.app = app
        # Views the workspace always has; they are not tabs and never close.
        self.resident: dict[str, Callable[[], SessionScope]] = {WELCOME: welcome_view}
        self.views: dict[str, SessionScope] = {}
        self.source: WorkspaceSource = DetachedWorkspaceSource()

    def require(self, identity: str) -> SessionScope:
        return self.views[identity]

    def origin(self, identity: str) -> SessionOrigin:
        """The original source, or its explicit unavailable member once closed."""
        if (
            self.app.session_navigation.get(identity) is not None
            or identity in self.resident
        ):
            if view := self.views.get(identity):
                return view.origin
        return NoSessionOrigin(identity)

    async def prepare(self, identity: str) -> SessionScope:
        if view := self.views.get(identity):
            return view
        await self.app._init_mode("workspace")
        view = (self.app.session_navigation.get(identity) or self.resident[identity])()
        view.id = identity
        view.display = False
        self.views[identity] = view
        host = self.app.workspace_screen.query_one(SessionHost)
        await host.mount(view)
        if identity not in self.views:
            raise SessionStartFailed(identity)
        return view

    async def select(self, identity: str) -> SessionScope:
        destination = await self.prepare(identity)
        if self.source.shown(destination):
            return destination
        departing = self.source
        await self.retire()
        # The loop runs due input and timers between the steps (the switch holds the frames).
        await after_input()
        # The preceding frame certifies the departing source. Revoke it before
        # LoadingWorkspaceSource admits any destination preparation callbacks.
        self.app.workspace_screen.frame_presentation.begin()
        self.source = LoadingWorkspaceSource(destination)
        # The arriving tree must participate in layout before its saved rows
        # can be prepared. Frames remain held by the navigation owner.
        departing.hide()
        destination.display = True
        await self.app.workspace_chrome.select(destination)
        await destination.prepare_presentation()
        await after_input()
        destination.activate_session()
        if destination.AUTO_FOCUS:
            if target := destination.query_one_optional(destination.AUTO_FOCUS):
                target.focus(scroll_visible=False)
        self.source = ShownWorkspaceSource(destination)
        return destination

    async def retire(self) -> None:
        self.source = await self.source.retire()

    @property
    def source(self) -> WorkspaceSource:
        return self._source

    @source.setter
    def source(self, source: WorkspaceSource) -> None:
        """Every change to the selected source passes here: the selected view is published, and
        consumers derive its target from it on read."""
        self._source = source
        self._publication = source.publication(self)

    def navigation_owner(self) -> NavigationOwner:
        """Derived from the selected view, so a closed or non-navigating view never answers."""
        return self.source.navigation_owner(self)

    def owns(self, view: SessionScope) -> bool:
        return self.source.current(view)

    def visible_target(self, root: Path | None) -> NavigationTarget:
        """The selected logical destination, including while a modal covers its frame."""
        return self._publication.target_for(root)

    def target_for_mode(self, identity: str, root: Path | None) -> NavigationTarget:
        """Resolve a transition's destination from its original workspace view."""
        view = self.views.get(identity)
        return (
            view.navigation_target
            if root is not None and view is not None and view.belongs_to_wire(root)
            else NoTarget()
        )

    def release_frame_callback(self, owner, callback) -> bool:
        """Admit mounted work through its original logical source binding.

        Hidden session mounts retain their same frame callback; workspace
        chrome has no session binding. The frame still owns widget attachment
        and terminal writes; the owner's message pump executes source I/O.
        """
        for view in owner.walk_ancestors(with_self=True):
            if isinstance(view, SessionScope):
                if not self.owns(view):
                    return False
                break
        owner.call_later(callback)
        return True

    def detach(self, identity: str) -> SessionScope | None:
        if view := self.views.pop(identity, None):
            if self.source.matches(view):
                self.source = DetachedWorkspaceSource()
            return view
        return None

    async def close(self, identity: str) -> None:
        if view := self.detach(identity):
            await self.finish(view)

    async def finish(self, view: SessionScope) -> None:
        await view.close_presentation()
        await view.remove()

    async def aclose(self) -> None:
        """Finalize owned sources while their frame and operational bindings exist."""
        await self.app.workspace_chrome.native.close()
        for view in tuple(self.views.values()):
            await view.close_presentation()
        self.source = DetachedWorkspaceSource()


class WorkspaceSessionShutdown:
    """Close session resources before Textual removes their message pumps."""

    async def _close_all(self) -> None:
        await self.workspace_sessions.aclose()
        await super()._close_all()
