"""Toad's cached access to the Comms service of the current route.

Core owns route selection and guarded writes (``agent_comms.route_selection``);
this view only caches the service it opened for one selection.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import Callable
from contextlib import ExitStack
from typing import TYPE_CHECKING, TypeVar
from functools import partial
from agent_comms.route_selection import RouteSelection, root_is_current, run_selected_write
from toad.core.events import CoreEventStream, CoordinationObserved, OpenTabsChanged

if TYPE_CHECKING:
    from agent_comms.comms import Comms
    from agent_comms.presentation import WireRevision

T = TypeVar("T")


@dataclass(frozen=True)
class ObservedCommsService:
    selection: RouteSelection
    service: Comms


class CoordinationAccess:
    """A validated core route owns cached access and guarded UI write admission."""

    def __init__(self, preparation) -> None:
        self.observation: ObservedCommsService | None = None
        self.events = CoreEventStream(self)
        self.revision: WireRevision | None = None
        self.route_stamp: tuple[tuple[int, int, int, int] | None, ...] | None = None
        self.task: asyncio.Task[None] | None = None
        self.timer = None
        self.custody = ExitStack()
        self.preparation = preparation
        # The application's existing retained sidebar publication lives with
        # its acquired service. Native views borrow it; they do not reread or
        # recapture the same worktree publication independently.
        self.sidebar_snapshot = None
        self.sidebar_lock = asyncio.Lock()

    @property
    def observed_service(self) -> Comms | None:
        return self.observation.service if self.observation else None

    @property
    def service(self) -> Comms:
        return self.require(RouteSelection.capture())

    def require(self, selected: RouteSelection) -> Comms:
        from agent_comms.comms import wire

        if RouteSelection.capture() != selected:
            raise ValueError("Comms route changed before the operation")
        observed = self.observation
        if observed is not None and observed.selection == selected:
            return observed.service
        with ExitStack() as acquisition:
            acquisition.enter_context(selected.route.admit_client())
            service = wire(selected.route)
            if service.root.resolve() != selected.root or RouteSelection.capture() != selected:
                raise ValueError("Comms route changed while opening the service")
            self.custody.enter_context(acquisition.pop_all())
        self.observation = ObservedCommsService(selected, service)
        self.revision = None
        self.route_stamp = None
        self.sidebar_snapshot = None
        return service

    async def read_sidebar(self, app, service: Comms, filters: tuple[bool, bool]):
        """Acquire one original viewer publication for its native consumers.

        The service, revision, viewer worktree and declared filters are the
        actual read scope. Sidebar rows and channel composers borrow this same
        publication only with their own matching declared filters. A retained
        view may borrow paint after activation,
        but route replacement revokes this acquisition before delivery.
        """
        from toad.sidebar_snapshot import SidebarSnapshot

        async with self.sidebar_lock:
            if (service is not self.observed_service
                    or not await self.preparation.run_thread(root_is_current, service.root)):
                raise ValueError("Sidebar service changed before acquisition")
            revision = await self.preparation.run_thread(service.views.revision)
            if (service is not self.observed_service
                    or not await self.preparation.run_thread(root_is_current, service.root)):
                raise ValueError("Sidebar service changed while observing its revision")
            if self.sidebar_snapshot is not None and self.sidebar_snapshot.matches(
                    service, revision, app.project_dir, filters):
                return self.sidebar_snapshot
            state = await self.preparation.run_thread(partial(
                service.views.viewer_snapshot, str(app.project_dir),
                show_stopped=filters[0], show_archived=filters[1]))
            snapshot = await SidebarSnapshot.capture(app, service, state, revision)
            if (service is not self.observed_service
                    or not await self.preparation.run_thread(root_is_current, service.root)):
                raise ValueError("Sidebar service changed during acquisition")
            previous_tabs = app.open_tabs
            self.sidebar_snapshot = snapshot
            # Only the acquired publication changes tab facts. Borrowers and
            # local route reprojections must not broadcast that change again.
            if app.open_tabs != previous_tabs:
                app.events.publish(OpenTabsChanged())
            return snapshot

    def start(self, app) -> None:
        """One application revision observer serves visible views and roster paint."""
        from toad.constants import COMMS_REFRESH_INTERVAL

        self.timer = app.set_interval(COMMS_REFRESH_INTERVAL, self.refresh)
        self.refresh()

    async def close(self) -> None:
        if self.timer is not None:
            self.timer.stop()
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.custody.close()

    def current_route_stamp(self) -> tuple[tuple[int, int, int, int] | None, ...]:
        from agent_comms.active_route import active_route_path
        from agent_comms.store_files import file_revision

        service = self.observed_service
        return (file_revision(active_route_path()),
                file_revision(service.root / "bus_meta.json") if service else None)

    async def route_changed(self) -> bool:
        stamp = await self.preparation.run_thread(self.current_route_stamp)
        return self.route_stamp is None or stamp[0] != self.route_stamp[0]

    def refresh(self) -> None:
        if self.task is not None and not self.task.done():
            return
        self.task = asyncio.create_task(self.observe())

    async def observe(self) -> None:
        try:
            service = self.observed_service
            route_stamp = await self.preparation.run_thread(self.current_route_stamp)
            revision = await self.preparation.run_thread(service.views.revision) if service else None
            if (service is not None and service is self.observed_service and revision == self.revision
                    and route_stamp == self.route_stamp):
                return
        except (OSError, ValueError, RuntimeError):
            # A route publication may be replacing its marker. Its next revision
            # retries validation; no sidebar visibility can disable observation.
            return

        try:
            service = await self.preparation.run_thread(lambda: self.service)
            route_stamp = await self.preparation.run_thread(self.current_route_stamp)
            revision = await self.preparation.run_thread(service.views.revision)
            if not await self.preparation.run_thread(root_is_current, service.root):
                raise ValueError("Observed Comms route changed before publication")
            if (service is not self.observed_service
                    or await self.preparation.run_thread(self.current_route_stamp) != route_stamp):
                return
        except (OSError, ValueError, RuntimeError):
            # Invalidation must also reach mounted views when validation fails.
            # They retain their original read/route fence and show unavailable;
            # a change notification never certifies a presentation or a send.
            pass
        self.revision, self.route_stamp = revision, route_stamp
        self.events.publish(CoordinationObserved(revision))

    def write(self, selected: RouteSelection, operation: Callable[..., T], *args: object, **kwargs: object) -> T:
        # This method runs in the same worker as the actual sink. The existing
        # core route lock is held through the operation; no second lock/store.
        return run_selected_write(selected.root, operation, *args, implicit=selected.implicit, **kwargs)

