"""Context measurement owns availability, provenance and visible projection."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import floor
from typing import NamedTuple
from textual.content import Content

class Cost(NamedTuple):
    """A cost with associated currency."""

    amount: float
    currency: str

    def __str__(self) -> str:
        return f"{self:}"

    def __format__(self, _specifier: str) -> str:
        from format_currency import format_currency

        amount, currency = self
        currency_text = format_currency(amount, currency_code=currency).replace(" ", "")
        return currency_text


class ContextMeasurement(ABC):
    available = False

    @abstractmethod
    def status(self) -> Content: ...

    @classmethod
    def saved(cls, usage):
        if usage is None:
            return ContextUnavailable("Native owner has not reported context usage")
        return SavedContextMeasurement(usage.used, usage.size)

    @classmethod
    def live(cls, used, size, cost):
        # The ACP adapter uses zero usage after compaction as unmeasured.
        # Decode that boundary sentinel once; never paint it as known 0%.
        if used <= 0 or size <= 0:
            return ContextUnavailable("Native owner reported an invalid context budget")
        match cost:
            case {"amount": amount, "currency": currency}:
                return LiveContextMeasurement(used, size, Cost(amount, currency))
            case _:
                return LiveContextMeasurement(used, size)


@dataclass(frozen=True)
class ContextUnavailable(ContextMeasurement):
    reason: str

    def status(self):
        return Content(f"Context unavailable · {self.reason}")


@dataclass(frozen=True)
class MeasuredContext(ContextMeasurement):
    used: int
    size: int
    cost: Cost | None = None
    available = True
    source_label = ""

    @property
    def percentage_used(self):
        return self.used / self.size * 100

    @property
    def percentage_display(self):
        return f"{floor(self.percentage_used * 10) / 10:.1f}%"

    def status(self):
        parts = [Content.assemble(f"{self.used / 1000:.1f}K (",
                  (self.percentage_display, "bold"), ")")]
        if self.source_label:
            parts.append(Content(self.source_label))
        if self.cost is not None:
            parts.append(Content.assemble((f"{self.cost}", "bold")))
        return Content(" • ").join(parts)


class LiveContextMeasurement(MeasuredContext):
    pass


class SavedContextMeasurement(MeasuredContext):
    source_label = "last response"
