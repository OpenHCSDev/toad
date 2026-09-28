"""Toad's view of the canonical Comms default root.

The core route owner validates the current selection and private marker without
constructing a service. Write admission remains separately guarded at its sink.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


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
