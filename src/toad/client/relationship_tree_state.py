"""Toolkit-neutral per-session UI state the thread-comms sidebar keeps between view binds.

Both Textual's `ThreadCommsSidebar` and Qt's `QtThreadCommsPanel` keep this across tab
switches so a conversation reopens with its last-selected row and its group-expansion state,
rather than resetting each time.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RelationshipTreeState:
    expanded: dict[type, bool] = field(default_factory=dict)
    selected: tuple[type, tuple[str, str]] | None = None
    selected_targets: tuple[tuple[type, tuple[str, str]], ...] = ()
