"""Logical session membership; Textual owns only the persistent native frame."""
from collections.abc import Callable
from abc import abstractmethod
from typing import TYPE_CHECKING
from textual._time import after_input
from textual.containers import Container
from agent_comms.declared_family import DeclaredFamily

from toad.constants import WELCOME

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.session_view import SessionOrigin, SessionView


def welcome_view() -> "SessionView":
    from toad.screens.welcome import WelcomeScreen

    return WelcomeScreen()


class WorkspaceSource(DeclaredFamily, affix="WorkspaceSource"):
    """Owns the selected view, including closing it outside the workspace."""

    @abstractmethod
    def matches(self, view: "SessionView") -> bool: ...

    def current(self, view: "SessionView") -> bool:
        return False

    def shown(self, view: "SessionView") -> bool:
        return False

    @abstractmethod
    async def retire(self) -> "WorkspaceSource": ...

    @abstractmethod
    def hide(self) -> None: ...

    @abstractmethod
    def commands(self) -> set: ...

    @abstractmethod
    def coordination_root(self): ...

    @abstractmethod
    def sidebar_focus_target(self): ...

    @abstractmethod
    def sidebars(self):
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

    def sidebar_focus_target(self):
        return None

    def sidebars(self):
        return ()


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

    def sidebar_focus_target(self):
        return self.view.sidebar_focus_target()

    def sidebars(self):
        return self.view.sidebars()


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
        # Views the workspace always has; they are not tabs and never close.
        self.resident: dict[str, Callable[[], SessionView]] = {WELCOME: welcome_view}
        self.views: dict[str, SessionView] = {}
        self.source: WorkspaceSource = DetachedWorkspaceSource()

    def require(self, identity: str) -> "SessionView":
        return self.views[identity]

    def origin(self, identity: str) -> "SessionOrigin | None":
        """What sessions and histories requested from ``identity`` start from; None once it closed."""
        if self.app.session_navigation.get(identity) is not None or identity in self.resident:
            if view := self.views.get(identity):
                return view.origin
        return None

    async def prepare(self, identity: str) -> "SessionView":
        if view := self.views.get(identity):
            return view
        view = (self.app.session_navigation.get(identity) or self.resident[identity])()
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
        departing = self.source
        await self.retire()
        # The loop runs due input and timers between the steps (the switch holds the frames).
        await after_input()
        # The preceding frame certifies the departing source. Revoke it before
        # LoadingWorkspaceSource admits any destination preparation callbacks.
        self.app.workspace_screen.frame_presentation.begin()
        self.source = LoadingWorkspaceSource(destination)
        await destination.prepare_presentation()
        # Preparation joins the arriving tree's existing rows. The workspace
        # alone swaps the two mounted trees, without a frame between them.
        departing.hide()
        destination.display = True
        await self.app.workspace_chrome.select(destination)
        await after_input()
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

    def visible_target(self, root):
        """The selected logical destination, including while a modal covers its frame."""
        view = self.source.view
        return self.target_for_mode(view.id, root) if view is not None and self.owns(view) else None

    def target_for_mode(self, identity, root):
        """Resolve a transition's destination from its original workspace view."""
        view = self.views.get(identity)
        return view.navigation_target_name if root is not None and view is not None and view.belongs_to_wire(root) else None

    def release_frame_callback(self, owner, callback) -> bool:
        """Admit mounted work through its original logical source binding.

        Hidden session mounts retain their same frame callback; workspace
        chrome has no session binding. The frame still owns widget attachment
        and terminal writes; the owner's message pump executes source I/O.
        """
        from toad.screens.session_view import SessionView

        for view in owner.walk_ancestors(with_self=True):
            if isinstance(view, SessionView):
                if not self.owns(view):
                    return False
                break
        owner.call_later(callback)
        return True

    async def close(self, identity: str) -> None:
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
    """Close session resources before Textual removes their message pumps."""

    async def _close_all(self) -> None:
        await self.workspace_sessions.aclose()
        await super()._close_all()
