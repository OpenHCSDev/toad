"""Logical session membership; Textual owns only the persistent native frame."""
from collections.abc import Callable
from abc import abstractmethod
from typing import TYPE_CHECKING
from textual.containers import Container
from agent_comms.declared_family import DeclaredFamily

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.session_view import SessionView


class WorkspaceSource(DeclaredFamily, affix="WorkspaceSource"):
    """Selected presentation custody, including retirement outside the workspace."""

    @abstractmethod
    def matches(self, view: "SessionView") -> bool: ...

    def current(self, view: "SessionView") -> bool:
        return False

    def shown(self, view: "SessionView") -> bool:
        return False

    @abstractmethod
    async def retire(self) -> "WorkspaceSource": ...

    @abstractmethod
    def commands(self) -> set: ...

    @abstractmethod
    def coordination_root(self): ...

    @abstractmethod
    def sidebar_focus_target(self): ...


class DetachedWorkspaceSource(WorkspaceSource):
    view = None
    identity = "workspace"

    def matches(self, view):
        return False

    async def retire(self):
        return self

    def commands(self):
        return set()

    def coordination_root(self):
        return None

    def sidebar_focus_target(self):
        return None


class BoundWorkspaceSource(WorkspaceSource):
    def __init__(self, view: "SessionView") -> None:
        self.view = view

    @abstractmethod
    def current(self, view: "SessionView") -> bool: ...

    @property
    def identity(self):
        return self.view.id

    def matches(self, view):
        return self.view is view

    async def retire(self):
        self.view.display = False
        await self.view.retire_presentation()
        return ParkedWorkspaceSource(self.view)

    def commands(self):
        return self.view.COMMANDS

    def coordination_root(self):
        return self.view.coordination_root

    def sidebar_focus_target(self):
        return self.view.sidebar_focus_target()


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


class WorkspaceSessions:
    def __init__(self, app: "ToadApp") -> None:
        self.app = app
        self.factories: dict[str, Callable[[], SessionView]] = {}
        self.views: dict[str, SessionView] = {}
        self.source: WorkspaceSource = DetachedWorkspaceSource()

    def register(self, identity: str, factory: "Callable[[], SessionView]") -> None:
        if identity in self.factories:
            raise ValueError(f"Logical session already registered: {identity}")
        self.factories[identity] = factory

    def require(self, identity: str) -> "SessionView":
        return self.views[identity]

    async def prepare(self, identity: str) -> "SessionView":
        if view := self.views.get(identity):
            return view
        view = self.factories[identity]()
        view.id = identity
        view.display = False
        self.views[identity] = view
        host = self.app.workspace_screen.query_one("#workspace-session-host", Container)
        await host.mount(view)
        return view

    async def select(self, identity: str) -> "SessionView":
        destination = await self.prepare(identity)
        if self.source.shown(destination):
            return destination
        await self.retire()
        # The preceding frame certifies the departing source. Revoke it before
        # LoadingWorkspaceSource admits any destination preparation callbacks.
        self.app.workspace_screen.frame_presentation.begin()
        self.source = LoadingWorkspaceSource(destination)
        destination.display = True
        await self.app.workspace_chrome.select(destination)
        await destination.prepare_presentation()
        destination.activate_session()
        if destination.AUTO_FOCUS:
            if target := destination.query_one_optional(destination.AUTO_FOCUS):
                target.focus(scroll_visible=False)
        self.source = ShownWorkspaceSource(destination)
        return destination

    async def retire(self) -> None:
        self.source = await self.source.retire()

    def owns(self, view: "SessionView") -> bool:
        return self.source.current(view)

    async def close(self, identity: str) -> None:
        self.factories.pop(identity, None)
        if view := self.views.pop(identity, None):
            if self.source.matches(view):
                self.source = DetachedWorkspaceSource()
            await view.close_presentation()
            await view.remove()

    async def aclose(self) -> None:
        """Finalize owned sources while their frame and operational bindings exist."""
        await self.app.workspace_chrome.native.close()
        for view in tuple(self.views.values()):
            await view.close_presentation()
        self.source = DetachedWorkspaceSource()


class WorkspaceSessionShutdown:
    """Finalize domain custody before Textual prunes its native message pumps."""

    async def _close_all(self) -> None:
        await self.workspace_sessions.aclose()
        await super()._close_all()
