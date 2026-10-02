"""Validated observation of the shared coordination service; no independent store."""
from __future__ import annotations
from toad.core import events as core_events
import asyncio
from dataclasses import dataclass
from agent_comms.comms import Comms, wire
from agent_comms.presentation import WireRevision
from toad.preferences import SidebarSettings
from toad.settings import PreferenceChange
from toad.core.events import SessionChangedEvent
from toad.sidebar_snapshot import SidebarSnapshot
from toad.comms_root import current_root

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
        return self.lock.locked() or (task is not None and not task.done())

    async def close(self) -> None:
        task = self.task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def mount(self) -> None:
        from toad.comms_root import current_root
        from toad.screens.comms import CommsScreen
        app = self.sidebar.app
        try:
            root = current_root().resolve()
        except (OSError, ValueError, RuntimeError):
            self.sidebar.display = False
            return
        screen = self.sidebar.screen
        if isinstance(screen, CommsScreen) and not screen.belongs_to_wire(root):
            self.sidebar.display = False
            return
        service = app.coordination_access.service
        self.service = service if root == service.root else wire(root)
        self.sidebar.subscribe_core(app.session_tracker.events)
        self.sidebar.observe_core(app.events)
        app.settings_changed_signal.subscribe(self.sidebar, self.settings_changed)
        app.coordination_observed.subscribe(self.sidebar, self.coordination_updated)
        self.sidebar.navigation.prepare()
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
        return SidebarSnapshot.capture(self.sidebar.app, self.service, state)

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

    async def session_updated(self, event: SessionChangedEvent) -> None:
        if not self.accepts_observation():
            return
        # Session routes/title changes are local projection facts. The wire's
        # own revision invalidates its snapshot; do not force a full history
        # read whenever a selected rich Conversation is reconstructed.
        if self.sidebar.projection.has_snapshot():
            await self.sidebar.projection.publish(self.project(self.sidebar.projection.snapshot.wire))
        self.sidebar.navigation.mode_changed(self.sidebar.app.selected_mode)
        self.refresh()

    async def sync(self) -> None:
        """Reconcile tracked rows before a resumed screen accepts input."""
        async with self.lock:
            revision = self.service.views.revision()
            if self.sidebar.projection.has_snapshot() and self.read_identity(revision) == self.identity:
                await self.sidebar.projection.publish(self.project(self.sidebar.projection.snapshot.wire))
            else:
                await self.read(revision)

    async def actions_changed(self, _update: None) -> None:
        if not self.accepts_observation():
            self.identity = None
            return
        if self.sidebar.projection.has_snapshot() and self.sidebar.is_attached:
            await self.sidebar.projection.publish(self.sidebar.projection.snapshot)
        self.identity = None
        self.refresh()

    async def present_cached(self) -> None:
        """Paint the last observed projection; refresh disk state after activation."""
        if not self.accepts_observation():
            return
        state = self.sidebar.app._sidebar_snapshot
        if state is not None and (
            state.show_stopped, state.show_archived
        ) == self.visible_filters:
            await self.sidebar.projection.publish(self.project(state))
        # A cold tab has no last-known projection. Do not read the entire wire
        # synchronously inside prepare_navigation before its first painted frame.
        self.after_frame()

    @property
    def visible_filters(self) -> tuple[bool, bool]:
        settings = self.sidebar.app.settings
        return settings.sidebar.show_stopped, settings.sidebar.show_archived

    def settings_changed(self, update: PreferenceChange) -> None:
        if update.field in {SidebarSettings.show_stopped, SidebarSettings.show_archived}:
            self.identity = None
            self.refresh()

    def registry_names(self) -> list[str]:
        """Registered thread names on the wire (for view toggles)."""
        try:
            local_threads = self.sidebar.app.local_coordination_threads()
            return [
                name
                for name in wire(current_root()).registry.active_threads()
                if name not in local_threads
            ]
        except Exception:
            return []

    def route_changed(self) -> bool:
        return self.sidebar.app.coordination_access.route_changed()

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
        try:
            # Retained inactive rosters reconcile on activation. Do not queue
            # source reads for every hidden tab; stack lookup may fail during
            # ordinary shutdown and belongs inside this existing error boundary.
            if self.sidebar.screen is not self.sidebar.app.screen:
                return
            if self.route_changed():
                self.sidebar.display = False
            if self.pending:
                return
            revision = self.service.views.revision()
            if self.sidebar.display and self.read_identity(revision) == self.identity:
                return
            self.task = asyncio.create_task(self.refresh_checked(revision))
        except Exception:
            self.sidebar.display = False

    async def refresh_checked(self, revision: WireRevision) -> None:
        service = self.service
        try:
            from toad.comms_root import root_is_current

            if not await asyncio.to_thread(root_is_current, service.root):
                if self.service is service:
                    self.sidebar.display = False
                return
            if self.service is not service or not self.sidebar.accepts_publication():
                return
            await self.poll(revision)
            if self.service is service and self.identity == self.read_identity(revision):
                if not await asyncio.to_thread(root_is_current, service.root):
                    return
                if self.service is not service:
                    return
                self.sidebar.display = True
                if not self.sidebar.navigation.ready.is_set():
                    self.sidebar.call_after_refresh(self.sidebar.navigation.finish, self.sidebar.navigation.revision)
        except Exception:
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
                revision = service.views.revision()
                if self.service is not service:
                    return
                if self.identity == self.read_identity(revision):
                    self.identity = self.read_identity(revision)
                    await self.sidebar.projection.publish(self.project(self.sidebar.projection.snapshot.wire))
                    return
            await self.read(revision)

    async def read(self, revision: WireRevision) -> None:
        service = self.service
        try:
            actor = self.sidebar.session_thread
            filters = self.visible_filters
            await self.sidebar.app.mark_visible_thread_read()
            state = await asyncio.to_thread(
                service.views.viewer_snapshot, str(self.sidebar.app.project_dir),
                show_stopped=filters[0], show_archived=filters[1],
            )
            if self.service is not service or not self.sidebar.accepts_publication():
                return
            if SidebarReadIdentity(revision, actor, filters) != self.read_identity(revision):
                return
            from toad.comms_root import root_is_current

            if not await asyncio.to_thread(root_is_current, service.root):
                if self.service is service:
                    self.sidebar.display = False
                return
            if self.service is not service:
                return
            snapshot = self.project(state)
            if state.read_marker_notice != self.read_marker_notice:
                self.read_marker_notice = state.read_marker_notice
                if state.read_marker_notice:
                    self.sidebar.notify(
                        state.read_marker_notice,
                        title="Read positions",
                        severity="warning",
                    )
            app = self.sidebar.app
            previous_tabs = app.open_tabs
            app._sidebar_snapshot = state
            self.identity = SidebarReadIdentity(revision, actor, filters)
            await self.sidebar.projection.publish(snapshot)
            # Admissions own tab labels/unread, not the wire's observation
            # metadata. Heartbeats and unrelated channel activity must not
            # invalidate every Conversation's goal and relationship readers.
            if app.open_tabs != previous_tabs:
                app.events.publish(core_events.OpenTabsChanged())
        except (OSError, ValueError):
            # An external writer may be replacing/recovering the wire. Retry on
            # the next poll without blocking or terminating the view.
            return
