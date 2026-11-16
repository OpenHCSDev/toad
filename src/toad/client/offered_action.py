"""Something a frontend offers a reader under a label."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class OfferedAction:
    """One choice a frontend lists under its label, such as an application menu entry or
    what holding a finger on a bus row offers; choosing it runs it."""

    label: str
    run: Callable[[], object]
