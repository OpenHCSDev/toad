"""Shared command context, target actions and command discovery.

Native menu/dialog/clipboard operations stay on native members.
The shared contract owns target selection, command availability,
action state and the absent/held execution family.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class TargetActionState(ABC):
    """Whether a thread has a pending target action. The family's absent
    member is NoTargetAction; the active member is ThreadActionExecution."""

    @property
    @abstractmethod
    def is_pending(self) -> bool: ...

    @abstractmethod
    def summary(self, row: object) -> str:
        """Status text for a sidebar row. The absent member uses the row's
        own summary; the active member uses the action's pending text."""

    @abstractmethod
    def busy(self, row: object) -> bool:
        """Whether the sidebar row shows busy state."""


class NoTargetAction(TargetActionState):
    """No pending action for this thread. One lookup, no reconstruction."""

    @property
    def is_pending(self) -> bool:
        return False

    def summary(self, row: object) -> str:
        return getattr(row, "summary", "")

    def busy(self, row: object) -> bool:
        return getattr(row, "working", False)
