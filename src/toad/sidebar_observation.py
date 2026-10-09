"""Validated observation of the shared coordination service; no independent store."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from agent_comms.comms import Comms
from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision
from agent_comms.presentation import WireRevision
from toad.preferences import SidebarSettings
from toad.core.preference_events import PreferenceChanged
from toad.core.events import SessionChangedEvent

@dataclass(frozen=True)
class SidebarReadIdentity:
    revision: WireRevision
    actor: str
    filters: tuple[bool, bool]

class SidebarObservation:
    def __init__(self, sidebar, *, enabled: bool):
        self.sidebar = sidebar
        self.enabled = enabled
        self.service = None
        self.task = None
        self.lock = asyncio.Lock()
        self.identity = None
        self.read_marker_notice = None

    @property
    def pending(self) -> bool:
        task = self.task
        return self.lock.locked() or (task is not None and not task.is_finished)

    async def close(self) -> None:
        task = self.task
        if task is not None:
            task.cancel()
            # A failed observation was already raised to the app by its worker.
            await asyncio.gather(task.wait(), return_exceptions=True)

    async def mount(self) -> None:
        from toad.screens.comms import CommsScreen
        app = self.sidebar.app
        try:
            service = await app.preparation.run_thread(lambda: app.coordination_access.service)
        except (OSError, ValueError, RuntimeError):
            self.sidebar.display = False
            return
        screen = self.sidebar.screen
        if isinstance(screen, CommsScreen) and not screen.belongs_to_wire(service.root):
            self.sidebar.display = False
            return
        self.service = service
        self.sidebar.subscribe_core(app.session_tracker.events)
        self.sidebar.observe_core(app.events)
        self.sidebar.observe_core(app.settings.events)
        self.sidebar.observe_core(app.coordination_access.events)
        await self.sidebar.navigation.prepare()
        from toad.screens.workspace import WorkspaceScreen
        if isinstance(screen, WorkspaceScreen):
            screen.frame_presentation.defer(self.sidebar, self.sidebar.navigation.start)
        self.after_frame()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.sidebar.projection.sync_spinner()

    def read_identity(self, revision: WireRevision) -> SidebarReadIdentity:
        return SidebarReadIdentity(revision, self.sidebar.session_thread, self.visible_filters)

    def project(self, state):
        return state.project(self.sidebar.app, self.service)

    def invalidate(self) -> None:
        self.identity = None

    def after_frame(self) -> None:
        from toad.screens.workspace import WorkspaceScreen

        screen = self.sidebar.screen
        if isinstance(screen, WorkspaceScreen):
            screen.frame_presentation.defer(self.sidebar, self.start_read)
        else:
            self.sidebar.call_after_refresh(self.start_read)

    async def bind(self, service: Comms) -> None:
        """Rebind shared navigation only through the app's validated route owner."""
        if self.service is service:
            return
        self.sidebar.display = False
        async with self.sidebar.projection.lock:
            self.service = service
            self.sidebar.projection.snapshot = None
            self.identity = None
            self.sidebar.navigation.reset()
            self.sidebar.projection.sync_spinner()
            # Retained rows belong to the admitted service, not merely names
            # shared by two roots. A real rebind retires that native roster.
            await self.sidebar.remove_children()

    async def session_updated(self, event: SessionChangedEvent) -> None:
        if not self.accepts_observation():
            return
        # Session routes/title changes are local projection facts. The wire's
        # own revision invalidates its snapshot; do not force a full history
        # read whenever a selected rich Conversation is reconstructed.
        await self.sidebar.projection.sync_sessions()
        self.sidebar.sync_current()
        self.refresh()

    async def sync(self) -> None:
        """Reconcile tracked rows before a resumed screen accepts input."""
        async with self.lock:
            revision = await self.sidebar.app.preparation.run_thread(self.service.views.revision)
            if self.sidebar.projection.has_snapshot() and self.read_identity(revision) == self.identity:
                await self.sidebar.projection.publish(self.project(self.sidebar.projection.snapshot))
            else:
                await self.read(revision)

    async def actions_changed(self, _update: None) -> None:
        if not self.accepts_observation():
            self.identity = None
            return
        if self.sidebar.projection.has_snapshot() and self.sidebar.is_attached:
            await self.sidebar.projection.actions_changed()
        self.identity = None
        self.refresh()

    async def present_cached(self) -> None:
        """Paint the last observed projection; refresh disk state after activation."""
        if not self.accepts_observation():
            return
        state = self.sidebar.app.coordination_access.sidebar_snapshot
        if state is not None and state.service is self.service and (
            state.wire.show_stopped, state.wire.show_archived
        ) == self.visible_filters:
            await self.sidebar.projection.publish(self.project(state))
        # A cold tab has no last-known projection. Do not read the entire wire
        # synchronously inside prepare_navigation before its first painted frame.
        self.after_frame()

    @property
    def visible_filters(self) -> tuple[bool, bool]:
        settings = self.sidebar.app.settings
        return settings.sidebar.show_stopped, settings.sidebar.show_archived

    def settings_changed(self, update: PreferenceChanged) -> None:
        if update.field in {SidebarSettings.show_stopped, SidebarSettings.show_archived}:
            self.identity = None
            self.refresh()

    async def route_changed(self) -> bool:
        return await self.sidebar.app.coordination_access.route_changed()

    async def coordination_updated(self, _event=None) -> None:
        service = self.sidebar.app.coordination_access.observed_service
        if service is not None:
            await self.bind(service)
        self.refresh()

    def accepts_observation(self) -> bool:
        from toad.widgets.side_bar import SideBar

        return (self.enabled and self.sidebar.accepts_publication()
                and not self.sidebar.query_ancestor(SideBar).collapsed)

    def refresh(self) -> None:
        if not self.accepts_observation():
            return
        if self.service is None:
            self.sidebar.display = False
            return
        self.after_frame()

    def start_read(self) -> None:
        if not self.accepts_observation():
            return
        from textual.app import ScreenStackError
        from textual.dom import NoScreen

        try:
            # Retained inactive rosters reconcile on activation. Do not queue
            # source reads for every hidden tab.
            current = self.sidebar.screen is self.sidebar.app.screen
        except (NoScreen, ScreenStackError):
            # Ordinary shutdown: this sidebar or the app no longer has a screen.
            self.sidebar.display = False
            return
        if not current or self.pending:
            return
        self.task = self.sidebar.run_worker(self.refresh_checked(), group="sidebar-observation")

    async def refresh_checked(self) -> None:
        service = self.service
        try:
            from agent_comms.route_selection import root_is_current

            if not await asyncio.to_thread(root_is_current, service.root):
                if self.service is service:
                    self.sidebar.display = False
                return
            if self.service is not service or not self.sidebar.accepts_publication():
                return
            revision = await self.sidebar.app.preparation.run_thread(service.views.revision)
            if self.service is not service or not self.sidebar.accepts_publication():
                return
            if (self.sidebar.display and self.sidebar.projection.has_snapshot()
                    and self.read_identity(revision) == self.identity):
                return
            await self.poll(revision)
            if self.service is service and self.identity is not None and (
                    self.identity == self.read_identity(self.identity.revision)):
                if not await asyncio.to_thread(root_is_current, service.root):
                    return
                if self.service is not service:
                    return
                self.sidebar.display = True
                if not self.sidebar.navigation.ready.is_set():
                    self.sidebar.call_after_refresh(self.sidebar.navigation.finish, self.sidebar.navigation.revision)
        except (OSError, ValueError, CoordinationReadUnavailable, StaleRevision) as error:
            # Same transient states as read(): an external writer is replacing
            # or recovering the wire; the next observation retries.
            self.sidebar.log.warning("Sidebar observation interrupted", error)
            return

    async def poll(self, revision: WireRevision) -> None:
        service = self.service
        async with self.lock:
            if self.service is not service:
                return
            if (self.sidebar.projection.has_snapshot() and self.read_identity(revision) == self.identity):
                # Selection changes the local route projection, not this
                # worktree-wide snapshot. A newly painted read cursor may
                # change its revision, so observe that write before reuse.
                await self.sidebar.app.mark_visible_thread_read()
                revision = await self.sidebar.app.preparation.run_thread(service.views.revision)
                if self.service is not service:
                    return
                if self.identity == self.read_identity(revision):
                    self.identity = self.read_identity(revision)
                    await self.sidebar.projection.publish(self.project(self.sidebar.projection.snapshot))
                    return
            await self.read(revision)

    async def read(self, revision: WireRevision) -> None:
        service = self.service
        try:
            actor = self.sidebar.session_thread
            filters = self.visible_filters
            await self.sidebar.app.mark_visible_thread_read()
            captured = await self.sidebar.app.coordination_access.read_sidebar(
                self.sidebar.app, service, filters)
            state = captured.wire
            if self.service is not service or not self.sidebar.accepts_publication():
                return
            if SidebarReadIdentity(revision, actor, filters) != self.read_identity(revision):
                return
            from agent_comms.route_selection import root_is_current

            if not await asyncio.to_thread(root_is_current, service.root):
                if self.service is service:
                    self.sidebar.display = False
                return
            if self.service is not service:
                return
            snapshot = self.project(captured)
            if state.read_marker_notice != self.read_marker_notice:
                self.read_marker_notice = state.read_marker_notice
                if state.read_marker_notice:
                    self.sidebar.notify(
                        state.read_marker_notice,
                        title="Read positions",
                        severity="warning",
                    )
            await self.sidebar.projection.publish(snapshot)
            # A captured wire revision is not a published roster. The original
            # projection retires its snapshot when native delivery is interrupted;
            # only its completed publication may suppress another observation.
            if self.sidebar.projection.snapshot is snapshot:
                self.identity = SidebarReadIdentity(captured.revision, actor, filters)
        except (OSError, ValueError) as error:
            # An external writer may be replacing/recovering the wire. Retry on
            # the next poll without blocking or terminating the view.
            self.sidebar.log.warning("Sidebar acquisition or publication interrupted", error)
            return
