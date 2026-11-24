"""Accepted ACP plan items and toolkit-independent status facts."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from acp.schema import PlanEntry


class PlanStatus(DeclaredFamily, affix="PlanStatus"):
    """ACP status names select their behavior once, when accepting a plan."""

    # How strongly an entry with this status shows, from 0 (invisible) to 1.
    opacity: ClassVar[float] = 1.0

    @classmethod
    @abstractmethod
    def marker(cls) -> str: ...

    @classmethod
    def newly_complete(cls, prior: type[PlanStatus] | None) -> bool:
        """Whether reaching this status from ``prior`` is a fresh completion."""
        return False

    @classmethod
    def style_qt_label(cls, label) -> None:
        """Apply status-specific styling (e.g. strikeout) to a Qt plan row label."""

    @classmethod
    def present_textual(cls, text, state: PlanDisplayState, entry: PlanItem) -> None:
        """Apply status-specific presentation to a Textual plan row."""


class PendingPlanStatus(PlanStatus):
    opacity = 0.6

    @classmethod
    def marker(cls) -> str:
        return " • "


class InProgressPlanStatus(PlanStatus):
    @classmethod
    def marker(cls) -> str:
        return "👉 "


class CompletedPlanStatus(PlanStatus):
    @classmethod
    def marker(cls) -> str:
        return " ✔ "

    @classmethod
    def newly_complete(cls, prior: type[PlanStatus] | None) -> bool:
        return prior is not None and prior is not cls

    @classmethod
    def style_qt_label(cls, label) -> None:
        font = label.font()
        font.setStrikeOut(True)
        label.setFont(font)

    @classmethod
    def present_textual(cls, text, state: PlanDisplayState, entry: PlanItem) -> None:
        text.complete(animated=state.newly_complete(entry))


@dataclass(frozen=True)
class PlanItem:
    content: str
    priority: str
    status: type[PlanStatus]

    @classmethod
    def from_acp(cls, content: str, priority: str, status: str, **_extensions) -> PlanItem:
        """Bind SDK-validated external fields once; metadata is not presentation."""
        return cls(content, priority, PlanStatus.member_named(status))


def decode_plan(entries: list[PlanEntry]) -> list[PlanItem]:
    """Consume SDK-validated ACP entries; subsequent consumers trust these items."""
    return [PlanItem.from_acp(entry.content, entry.priority, entry.status) for entry in entries]


@dataclass
class PlanDisplayState:
    """Toolkit-neutral render state for a plan panel: the currently-displayed entries
    and the per-entry status from the previous render, so a frontend can animate the
    transition when an entry first reaches a completed status.

    Both Textual's `widgets/plan.Plan` and Qt's `qt/plan_panel.QtPlan` route their
    entries updates through `update(...)` and ask `newly_complete(entry)` to drive
    the same completion animation decision — one fact (did this item just complete?),
    one owner, both frontends in agreement."""

    entries: list[PlanItem] = field(default_factory=list)
    previous_statuses: dict[str, type[PlanStatus]] = field(default_factory=dict)

    def update(self, new_entries: list[PlanItem]) -> None:
        """Capture the current statuses as `previous_statuses` before replacing entries, so
        the next `newly_complete(entry)` call can tell which rows just transitioned."""
        self.previous_statuses = {entry.content: entry.status for entry in self.entries}
        self.entries = list(new_entries)

    def newly_complete(self, entry: PlanItem) -> bool:
        """Whether this entry's status is complete AND was not complete at the previous
        update — the condition both frontends use to animate the completion."""
        return entry.status.newly_complete(self.previous_statuses.get(entry.content))


class PlanView:
    """The agent's plan as a frontend lists it: Textual's `Plan` and Qt's `QtPlan` both
    inherit this. An empty plan says so; each entry is its status marker, then its text,
    struck through once complete and shown as strongly as its status says."""

    empty_plan_text = "No plan yet"

    @staticmethod
    def plan_rows(entries) -> tuple[tuple[str, PlanItem], ...]:
        return tuple((entry.status.marker(), entry) for entry in entries)
