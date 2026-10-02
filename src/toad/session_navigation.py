"""App admission and close use the existing workspace's declared factories."""
from __future__ import annotations
from toad.core import events as core_events
from toad.core.events import CoreEventStream

from collections.abc import Callable
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, cast
from functools import partial


from toad.comms_root import current_root, root_is_current
from toad.navigation_preparation import CommsNavigationRequest
from toad.session_admission import (HistorySessionAdmission, NativeSessionAdmission,
                                   PreviewSessionAdmission, SessionAdmission)
from toad.session_tracker import OpenTab, SessionDetails

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.conversation_kind import ConversationKind
    from toad.screens.main import MainScreen


class SessionAdmissions:
    def __init__(self, app: ToadApp, initial_session_id: str | None = None) -> None:
        self.app = app
        self.events = CoreEventStream(self)
        self.identities = count(1)
        self.initial_session_id = initial_session_id

    def default_source(self) -> MainScreen:
        from toad.screens.main import MainScreen
        app = self.app
        session_id = self.initial_session_id
        self.initial_session_id = None
        return MainScreen(app.project_dir, app.agent_data, agent_session_id=session_id).data_bind(column=type(app).column,
                column_width=type(app).column_width, scrollbar=type(app).scrollbar)


    async def reveal(self) -> None:
        from toad.widgets.comms_sidebar import CommsSidebar
        from toad.widgets.side_bar import SideBar, SideBarCollapsible
        app = self.app
        sidebar = app.screen.query_one_optional(CommsSidebar)
        if sidebar is None:
            sessions = app.session_tracker.ordered_sessions
            if not sessions:
                app.notify("No sessions are open", title="Sessions")
                return
            await app.select_session(sessions[-1].mode_name)
            sidebar = app.screen.query_one_optional(CommsSidebar)
        if sidebar is not None:
            sidebar.query_ancestor(SideBar).reveal()
            sidebar.query_ancestor(SideBarCollapsible).collapsed = False
            await sidebar.navigation.focus_current()

    @property
    def members(self) -> tuple[SessionAdmission, ...]:
        return tuple(cast(SessionAdmission, factory) for factory in self.app.workspace_sessions.factories.values())

    def get(self, mode: str) -> SessionAdmission | None:
        return cast(SessionAdmission | None, self.app.workspace_sessions.factories.get(mode))

    def find(self, address: object) -> SessionAdmission | None:
        return next((entry for entry in self.members if entry.address == address), None)

    def source(self, mode: str) -> MainScreen | None:
        admission = self.get(mode)
        return admission.source(self) if admission else None

    def publish(self) -> None:
        self.app.events.publish(core_events.OpenTabsChanged())
        self.app.update_show_sessions()

    async def admit(self, admission: SessionAdmission, *, after: str | None = None) -> str:
        app = self.app
        app.workspace_sessions.register(admission.mode, admission)
        app.tab_order.open(admission.mode, after=after)
        self.publish()
        await app.select_session(admission.mode)
        await admission.ready(self)
        return admission.mode

    async def new(self, factory: Callable[[], MainScreen], *, title: str = "New Session") -> SessionDetails:
        details = self.app.session_tracker.new_session(title=title)
        await self.admit(NativeSessionAdmission(details, factory))
        return details

    async def create_from(self, owner_mode: str) -> None:
        source = self.source(owner_mode)
        await self.new(source.spawn if source is not None and source.has_agent() else self.default_source)

    async def launch(self, agent_identity: str, *, agent_session_id: str | None = None,
                     session_pk: int | None = None, project_path: Path | None = None,
                     initial_prompt: str | None = None) -> None:
        from toad.agents import read_agents
        from toad.db import DB
        from toad.screens.main import MainScreen

        app = self.app
        agent, title = None, None
        if session_pk is not None:
            saved = await DB().session_get(session_pk)
            if saved is not None:
                title, agent = saved.title, saved.meta_json.agent_data
        if agent is None:
            agents = await read_agents()
            try:
                agent = agents[agent_identity]
            except KeyError:
                app.notify("Agent not found", title="Launch agent", severity="error")
                return
        project = project_path if project_path is not None else app.project_dir
        if agent_session_id is not None:
            existing = next((entry for entry in self.members
                             if entry.accepts_launch(self, agent_identity, agent_session_id)), None)
            if existing is not None:
                await app.select_session(existing.mode)
                return
        await self.new(lambda: MainScreen(project, agent, agent_session_id,
            session_pk=session_pk, initial_prompt=initial_prompt).data_bind(
            column=type(app).column, column_width=type(app).column_width, scrollbar=type(app).scrollbar),
            title=title or "New Session")

    async def history(self, *, owner_mode: str, project_path: Path, me: str, target: str,
                      kind: type[ConversationKind]) -> str:
        from toad.thread_navigation import ThreadOrigin

        app = self.app
        source = self.source(owner_mode)
        if source is None:
            app.notify("The owning agent tab was closed", title="Comms target unavailable", severity="error")
            return app.selected_mode
        origin = ThreadOrigin.capture(app, source)
        try:
            requested_root = str(current_root())
            prepared = await app.navigation_reader.read(CommsNavigationRequest(
                requested_root, owner_mode, me, target, kind, source.coordination_root))
        except Exception as error:
            app.notify(str(error), title="Comms target unavailable", severity="error")
            return app.selected_mode
        if prepared is None:
            return app.selected_mode
        if not origin.current(app.thread_navigation, owner_mode) or not root_is_current(requested_root):
            return app.selected_mode
        # History admission is the only owner of this typed key. Workspace
        # factories carry its identity, so no key-to-mode mirror can go stale.
        admission = self.find(kind.view_identity(prepared.key))
        if admission is None:
            admission = HistorySessionAdmission(f"comms-{next(self.identities)}", prepared.key, kind,
                                                project_path, prepared.recovery_root)
            await self.admit(admission)
        else:
            await app.select_session(admission.mode)
            await admission.ready(self)
        return admission.mode

    async def preview(self, path: Path) -> str:
        path = path.expanduser().resolve()
        entry = self.find(path)
        if entry is None:
            entry = PreviewSessionAdmission(f"preview-{next(self.identities)}", path, self.app.selected_mode)
            return await self.admit(entry, after=self.app.selected_mode)
        await self.app.select_session(entry.mode)
        return entry.mode

    def entered(self, mode: str, previous: str) -> None:
        if entry := self.get(mode):
            entry.entered(previous)

    async def return_from(self, mode: str) -> None:
        if entry := self.get(mode):
            await entry.return_to(self)

    @property
    def tabs(self) -> tuple[OpenTab, ...]:
        return self.app.tab_order.project({entry.mode: entry.tab(self, self.app._sidebar_snapshot)
                                          for entry in self.members})

    def sync_identity(self, owner: str, previous: str, current: str) -> None:
        for entry in self.members:
            entry.sync_identity(self, owner, previous, current)

    def sync_recovery(self, owner: str, root: str | None) -> None:
        for entry in self.members:
            entry.sync_recovery(self, owner, root)

    def sync_project(self, owner: str, project: Path) -> None:
        for entry in self.members:
            entry.sync_project(self, owner, project)

    async def close(self, mode: str) -> None:
        entry = self.get(mode)
        if entry is None:
            return
        closing = tuple(member for member in self.members if member.depends_on(mode))
        if any(member.mode == self.app.selected_mode for member in closing):
            await entry.return_to(self)
        for member in closing:
            member.forget(self)
        self.app.tab_order.close({member.mode for member in closing})
        # Retire membership before publication and slow widget exits. Delayed
        # opening metadata cannot revive a closed owner during teardown.
        for member in closing:
            self.app.workspace_sessions.factories.pop(member.mode)
        self.publish()
        for member in closing:
            await self.app.workspace_sessions.close(member.mode)
