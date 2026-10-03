"""Toad's view of the canonical Comms default root.

The core route owner validates the current selection and private marker without
constructing a service. Write admission remains separately guarded at its sink.
"""

from __future__ import annotations

import os
import asyncio
from dataclasses import dataclass
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar
from toad.core.events import CoreEventStream, CoordinationObserved

if TYPE_CHECKING:
    from agent_comms.active_route import CommsRoute
    from agent_comms.comms import Comms
    from agent_comms.presentation import WireRevision

T = TypeVar("T")


@dataclass(frozen=True)
class RouteSelection:
    route: CommsRoute
    root: Path
    implicit: bool

    @classmethod
    def capture(cls, source: str | Path | None = None) -> RouteSelection:
        from agent_comms.active_route import resolve_comms_route

        route = resolve_comms_route()
        selection = cls(route, route.observe_root(), implicit_root())
        if source is not None and Path(source).expanduser().resolve() != selection.root:
            raise ValueError("Comms route changed; reopen this view")
        return selection

    @classmethod
    def for_child(cls, env: Mapping[str, str], cwd: str | Path) -> RouteSelection:
        """Capture selection before projecting a root into a child environment."""
        from agent_comms.active_route import resolve_comms_route
        from toad.acp.maintenance_ingress import configured_root

        root = configured_root(env, cwd)
        implicit = "AGENT_COMMS_ROOT" not in env
        route = resolve_comms_route() if implicit else resolve_comms_route(root)
        if route.observe_root() != root:
            raise ValueError("ACP route changed while selecting its child")
        return cls(route, root, implicit)


@dataclass(frozen=True)
class ObservedCommsService:
    selection: RouteSelection
    service: Comms


class CoordinationAccess:
    """A validated core route owns cached access and guarded UI write admission."""

    def __init__(self, changed: Callable[[], None], preparation) -> None:
        self.observation: ObservedCommsService | None = None
        self.changed = changed
        self.events = CoreEventStream(self)
        self.revision: WireRevision | None = None
        self.route_stamp: tuple[tuple[int, int, int, int] | None, ...] | None = None
        self.task: asyncio.Task[None] | None = None
        self.timer = None
        self.custody = ExitStack()
        self.preparation = preparation

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
        self.changed()
        return service

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

    def route_changed(self) -> bool:
        return self.route_stamp is None or self.current_route_stamp()[0] != self.route_stamp[0]

    def refresh(self) -> None:
        if self.task is not None and not self.task.done():
            return
        try:
            service = self.observed_service
            route_stamp = self.current_route_stamp()
            revision = service.views.revision() if service else None
            if (service is not None and revision == self.revision
                    and route_stamp == self.route_stamp):
                return
            self.task = asyncio.create_task(self.observe(revision, route_stamp))
        except (OSError, ValueError, RuntimeError):
            # A route publication may be replacing its marker. Its next revision
            # retries validation; no sidebar visibility can disable observation.
            return

    async def observe(self, revision: WireRevision | None,
                      route_stamp: tuple[tuple[int, int, int, int] | None, ...]) -> None:
        try:
            service = await self.preparation.run_thread(lambda: self.service)
            route_stamp = self.current_route_stamp()
            revision = service.views.revision()
            if not await self.preparation.run_thread(root_is_current, service.root):
                raise ValueError("Observed Comms route changed before publication")
            if service is not self.observed_service or self.current_route_stamp() != route_stamp:
                return
        except (OSError, ValueError, RuntimeError):
            # Invalidation must also reach mounted views when validation fails.
            # They retain their original read/route fence and show unavailable;
            # a change notification never certifies a presentation or a send.
            pass
        self.revision, self.route_stamp = revision, route_stamp
        self.events.publish(CoordinationObserved())

    def write(self, selected: RouteSelection, operation: Callable[..., T], *args: object, **kwargs: object) -> T:
        # This method runs in the same worker as the actual sink. The existing
        # core route lock is held through the operation; no second lock/store.
        return run_selected_write(selected.root, operation, *args, implicit=selected.implicit, **kwargs)


def current_root() -> Path:
    """Resolve the explicit override or the validated default Comms route."""
    from agent_comms.active_route import resolve_comms_route

    return resolve_comms_route().observe_root()


def root_is_current(root: str | Path) -> bool:
    """Fail closed if a mounted view's root is no longer the current route."""
    try:
        return current_root() == Path(root).expanduser().resolve()
    except OSError, ValueError, RuntimeError:
        return False


def implicit_root() -> bool:
    """Capture whether this UI request selected the managed default route."""
    return "AGENT_COMMS_ROOT" not in os.environ


@contextmanager
def selected_write(root: str | Path, *, implicit: bool) -> Iterator[None]:
    """Guard one default-root side effect through the actual synchronous sink.

    The core owns the shared route-directory lock and publication protocol.
    Explicit overrides retain their prior independent-root behavior.
    """
    if implicit:
        from agent_comms.active_route import guard_default_route_write

        scope = guard_default_route_write(Path(root))
    else:
        scope = nullcontext()
    with scope:
        if implicit and not root_is_current(root):
            raise ValueError("default Comms route changed before write")
        yield


def run_selected_write(
    root: str | Path,
    operation: Callable[..., T],
    *args: object,
    implicit: bool,
    **kwargs: object,
) -> T:
    """Enter route admission inside the worker that actually performs the write."""
    with selected_write(root, implicit=implicit):
        return operation(*args, **kwargs)
