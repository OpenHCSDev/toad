"""Logical session membership; Textual owns only the persistent native frame."""
from collections.abc import Callable
from typing import TYPE_CHECKING
from textual.containers import Container

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.session_view import SessionView


class WorkspaceSessions:
    def __init__(self, app: "ToadApp") -> None:
        self.app = app
        self.factories: dict[str, Callable[[], SessionView]] = {}
        self.views: dict[str, SessionView] = {}
        self.selected: SessionView | None = None

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
        previous = self.selected
        if previous is destination:
            return destination
        if previous is not None:
            previous.capture_navigation()
            await previous.retire_presentation()
            previous.display = False
        self.selected = destination
        destination.display = True
        await self.app.workspace_chrome.select(destination)
        await destination.prepare_presentation()
        destination.activate_session()
        if destination.AUTO_FOCUS:
            if target := destination.query_one_optional(destination.AUTO_FOCUS):
                target.focus(scroll_visible=False)
        return destination

    async def close(self, identity: str) -> None:
        self.factories.pop(identity, None)
        if view := self.views.pop(identity, None):
            if self.selected is view:
                self.selected = None
            await view.remove()
