"""Admitted ACP plan items and their declaration-owned presentation."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar, TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from acp.schema import PlanEntry

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.content import Content
    from textual.widget import Widget
    from toad.widgets.strike_text import StrikeText


class PlanStatus(DeclaredFamily, affix="PlanStatus"):
    """ACP status names select their behavior once, at plan admission."""

    complete: ClassVar[bool] = False

    @classmethod
    @abstractmethod
    def marker(cls) -> Content: ...

    @classmethod
    def decorate(
        cls, text: StrikeText, owner: Widget, previous: type[PlanStatus] | None
    ) -> None:
        """An unfinished item has no completion decoration."""

    @classmethod
    def compose(
        cls, owner: Widget, item: PlanItem, previous: type[PlanStatus] | None
    ) -> ComposeResult:
        from textual.content import Content
        from toad.widgets.plan import NonSelectableStatic
        from toad.widgets.strike_text import StrikeText

        classes = f"priority-{item.priority} status-{cls.declared_name}"
        yield NonSelectableStatic(cls.marker(), classes=f"status {classes}")
        yield (text := StrikeText(Content(item.content), classes=f"plan {classes}"))
        cls.decorate(text, owner, previous)


class PendingPlanStatus(PlanStatus):
    @classmethod
    def marker(cls) -> Content:
        from textual.content import Content
        return Content(" • ")


class InProgressPlanStatus(PlanStatus):
    @classmethod
    def marker(cls) -> Content:
        from textual.content import Content
        return Content("👉 ")


class CompletedPlanStatus(PlanStatus):
    complete = True

    @classmethod
    def marker(cls) -> Content:
        from textual.content import Content
        return Content(" ✔ ")

    @classmethod
    def decorate(cls, text, owner, previous) -> None:
        if previous is not None and not previous.complete:
            owner.call_after_refresh(text.strike)
        else:
            text.add_class("-complete")


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
