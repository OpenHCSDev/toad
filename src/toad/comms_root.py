"""Toad's view of the canonical Comms default root.

The core wire factory owns active-route parsing and validates the private root
marker under its store lock. Toad must not interpret active-route.json itself.
"""

from __future__ import annotations

from pathlib import Path


def current_root() -> Path:
    """Resolve the explicit override or the validated default Comms route."""
    from agent_comms.operations import wire

    return wire().root.resolve()


def root_is_current(root: str | Path) -> bool:
    """Fail closed if a mounted view's root is no longer the current route."""
    try:
        return current_root() == Path(root).expanduser().resolve()
    except OSError, ValueError, RuntimeError:
        return False
