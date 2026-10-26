"""Thread opening tracks requests, avoids duplicates and opens native views."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.errors import RelationViolationError
from agent_comms.repo import Checkout
from toad.tab_identity.kinds import MailboxTab
from toad.navigation_preparation import (
    OpenThread,
    ThreadNavigationRequest,
    ThreadOpening,
)

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.main import MainScreen
    from toad.session_scope import ProjectSessionOrigin
    from toad.navigation_preparation import ThreadNavigation


@dataclass(frozen=True)
class ThreadOrigin:
    source: ProjectSessionOrigin
    selected_mode: str
    root: str | None
    identity: str

    @classmethod
    def capture(cls, app: ToadApp, source: ProjectSessionOrigin) -> ThreadOrigin:
        return cls(
            source,
            app.selected_mode,
            source.coordination_root,
            source.thread_identity.thread_name(),
        )

    def current(self, navigator: ThreadNavigator, owner_mode: str) -> bool:
        app = navigator.app
        if app.is_running and self.source.is_attached:
            if app.workspace_sessions.origin(owner_mode) is self.source:
                return self == self.capture(app, self.source)
        return False


class ThreadNavigator:
    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.pending: dict[tuple[str, str, str], ThreadOpening] = {}

    async def open(self, *, owner_mode: str, project_path: Checkout, target: str) -> str:
        app = self.app
        try:
            source = app.workspace_sessions.origin(owner_mode).require()
        except RelationViolationError:
            return app.selected_mode
        origin = ThreadOrigin.capture(app, source)
        access = app.coordination_access
        comms = await app.preparation.run_thread(
            lambda: access.observation.observed().service
        )
        requested_root = str(comms.root)
        if not origin.current(self, owner_mode):
            return app.selected_mode
        identity = await app.preparation.run_thread(
            lambda: MailboxTab(
                comms.registry.snapshot().require(target).incarnation, requested_root
            )
        )
        mounted_root = str(Path(requested_root).expanduser())
        open_threads = []
        for details in app.session_tracker.ordered_sessions:
            view = app.session_navigation.source(details.mode_name)
            if view is None:
                continue
            root, name = view.coordination_root, view.thread_identity.thread_name()
            if (root, name) == (mounted_root, target):
                await app.select_session(details.mode_name)
                return details.mode_name
            if root is not None:
                open_threads.append(OpenThread(details.mode_name, root, name))
        request = ThreadNavigationRequest(
            comms, target, project_path, tuple(open_threads)
        )
        key = owner_mode, request.root, request.target
        if pending := self.pending.get(key):
            return await asyncio.shield(pending.task)
        opening = ThreadOpening(self, owner_mode, request, origin, identity)
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

    async def mount_loading(self, opening: ThreadOpening) -> None:
        await self.app.session_navigation.new(
            opening.identity, lambda: opening.view, title=opening.request.target
        )

    async def mount(self, prepared: ThreadNavigation, opening: ThreadOpening) -> str:
        view = opening.view
        prepared.bind(view)
        self.app.session_navigation.bind_opened(
            view,
            original=(prepared.root, prepared.thread.incarnation),
            name=prepared.thread.name,
            project=prepared.project,
        )
        await view._prepare_content()
        await view.wait_content_ready()
        return (
            view.id
            if self.app.workspace_sessions.views.get(view.id) is view
            else self.app.selected_mode
        )
