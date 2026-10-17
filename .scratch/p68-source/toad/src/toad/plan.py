"""Admitted ACP plan items and toolkit-independent status facts."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.declared_family import DeclaredFamily
from acp.schema import PlanEntry


class PlanStatus(DeclaredFamily, affix="PlanStatus"):
    """ACP status names select their behavior once, at plan admission."""

    complete: ClassVar[bool] = False

    @classmethod
    @abstractmethod
    def marker(cls) -> str: ...


class PendingPlanStatus(PlanStatus):
    @classmethod
    def marker(cls) -> str:
        return " • "


class InProgressPlanStatus(PlanStatus):
    @classmethod
    def marker(cls) -> str:
        return "👉 "


class CompletedPlanStatus(PlanStatus):
    complete = True

    @classmethod
    def marker(cls) -> str:
        return " ✔ "


@dataclass(frozen=True)
class PlanItem:
    content: str
    priority: str
    status: type[PlanStatus]

    @classmethod
    def from_acp(cls, content: str, priority: str, status: str, **_extensions) -> PlanItem:
        """Bind SDK-validated external fields once; metadata is not presentation."""
        return cls(content, priority, PlanStatus.decode(status))


def decode_plan(entries: list[PlanEntry]) -> list[PlanItem]:
    """Consume SDK-validated ACP entries; subsequent consumers trust these items."""
    return [PlanItem.from_acp(entry.content, entry.priority, entry.status) for entry in entries]
