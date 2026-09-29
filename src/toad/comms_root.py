"""Toad's view of the canonical Comms default root.

The core route owner validates the current selection and private marker without
constructing a service. Write admission remains separately guarded at its sink.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from agent_comms.active_route import CommsRoute
    from agent_comms.comms import Comms

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


@dataclass(frozen=True)
class ObservedCommsService:
    selection: RouteSelection
    service: Comms


class CoordinationAccess:
    """A validated core route owns cached access and guarded UI write admission."""

    def __init__(self, changed: Callable[[], None]) -> None:
        self.observation: ObservedCommsService | None = None
        self.changed = changed

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
        service = wire()
        if service.root.resolve() != selected.root or RouteSelection.capture() != selected:
            raise ValueError("Comms route changed while opening the service")
        self.observation = ObservedCommsService(selected, service)
        self.changed()
        return service

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
