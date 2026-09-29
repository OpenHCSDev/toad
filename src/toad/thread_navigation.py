"""Thread opening owns intent, deduplication and native-view admission."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from toad.comms_root import current_root
from toad.navigation_preparation import OpenThread, ThreadNavigationRequest, ThreadOpening

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.main import MainScreen
    from toad.navigation_preparation import NativeThreadNavigation


@dataclass(frozen=True)
class ThreadOrigin:
    source: MainScreen
    selected_mode: str
    root: str | None
    identity: str

    @classmethod
    def capture(cls, app: ToadApp, source: MainScreen) -> ThreadOrigin:
        return cls(source, app.selected_mode, source.coordination_root, source._comms_thread)

    def current(self, navigator: ThreadNavigator, owner_mode: str) -> bool:
        app = navigator.app
        if app.is_running and self.source.is_attached:
            if owner_mode in app.workspace_sessions.factories:
                return self == self.capture(app, self.source)
        return False


class ThreadNavigator:
    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.pending: dict[tuple[str, str, str], ThreadOpening] = {}

    def source(self, owner_mode: str) -> MainScreen | None:
        from toad.screens.comms import CommsScreen

        source = self.app._main_session_screen(owner_mode)
        if source is not None:
            return source
        owner_view = self.app.workspace_sessions.views.get(owner_mode)
        if isinstance(owner_view, CommsScreen):
            return self.app._main_session_screen(owner_view.owner_mode)
        return None

    async def open(self, *, owner_mode: str, project_path: Path, target: str) -> str:
        app = self.app
        source = self.source(owner_mode)
        if source is None:
            return app.selected_mode
        try:
            requested_root = str(current_root())
        except (OSError, ValueError, RuntimeError) as error:
            app.notify(str(error), title="Thread unavailable", severity="error")
            return app.selected_mode
        mounted_root = str(Path(requested_root).expanduser())
        open_threads = []
        for details in app.session_tracker.ordered_sessions:
            view = app._main_session_screen(details.mode_name)
            if view is None:
                continue
            root, name = view.coordination_root, view._comms_thread
            if (root, name) == (mounted_root, target):
                await app.select_session(details.mode_name)
                return details.mode_name
            if root is not None:
                open_threads.append(OpenThread(details.mode_name, root, name))
        request = ThreadNavigationRequest(requested_root, target, project_path, tuple(open_threads))
        key = owner_mode, request.root, request.target
        if pending := self.pending.get(key):
            return await asyncio.shield(pending.task)
        opening = ThreadOpening(self, owner_mode, request, ThreadOrigin.capture(app, source))
        self.pending[key] = opening
        return await asyncio.shield(opening.task)

    def finished(self, opening: ThreadOpening) -> None:
        if self.pending.get(opening.key) is opening:
            del self.pending[opening.key]

    async def close(self) -> None:
        tasks = tuple(opening.task for opening in self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def mount(self, prepared: NativeThreadNavigation, opening: ThreadOpening) -> str:
        from toad.screens.main import MainScreen

        app = self.app
        agent = opening.origin.source._agent
        if agent is None:
            app.notify("The owning agent session is unavailable", title="Thread unavailable", severity="error")
            return opening.owner_mode

        def get_screen() -> MainScreen:
            screen = MainScreen(prepared.project, agent, agent_session_id=prepared.thread.name,
                                agent_session_title=prepared.thread.name)
            screen.initial_coordination_root = prepared.root
            screen._comms_thread = prepared.thread.name
            screen.set_reactive(MainScreen.column, app.column)
            screen.set_reactive(MainScreen.column_width, app.column_width)
            screen.set_reactive(MainScreen.scrollbar, app.scrollbar)
            screen.watch(app, "column", lambda value: setattr(screen, "column", value), init=False)
            screen.watch(app, "column_width", lambda value: setattr(screen, "column_width", value), init=False)
            screen.watch(app, "scrollbar", lambda value: setattr(screen, "scrollbar", value), init=False)
            return screen

        details = await app.new_session_screen(get_screen, title=prepared.thread.name)
        view = app._main_session_screen(details.mode_name)
        if view is not None:
            await view.wait_content_ready()
        return details.mode_name if app.workspace_sessions.views.get(details.mode_name) else app.selected_mode
