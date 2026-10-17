"""Context measurement owns availability, sources and shared status text."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import floor
from typing import NamedTuple
from rich.text import Text as RichText
from agent_comms.context_reading import ContextReading, UnmeasuredContext

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
    @abstractmethod
    def status(self) -> RichText: ...

    @classmethod
    def saved(cls, reading: ContextReading) -> ContextMeasurement:
        return SavedContextMeasurement(reading)

    @classmethod
    def live(cls, used, size, cost):
        # The ACP adapter uses zero usage after compaction as unmeasured.
        # Decode that boundary sentinel once; never paint it as known 0%.
        if used <= 0 or size <= 0:
            return SavedContextMeasurement(UnmeasuredContext())
        return LiveContextMeasurement(used, size, Cost(cost.amount, cost.currency) if cost else None)


@dataclass(frozen=True)
class LiveContextMeasurement(ContextMeasurement):
    used: int
    size: int
    cost: Cost | None = None

    @property
    def percentage_used(self):
        return self.used / self.size * 100

    @property
    def percentage_display(self):
        return f"{floor(self.percentage_used * 10) / 10:.1f}%"

    def status(self) -> RichText:
        parts = [RichText.assemble(f"{self.used / 1000:.1f}K (",
                  (self.percentage_display, "bold"), ")")]
        if self.cost is not None:
            parts.append(RichText.assemble((f"{self.cost}", "bold")))
        return RichText(" • ").join(parts)


@dataclass(frozen=True)
class SavedContextMeasurement(ContextMeasurement):
    reading: ContextReading

    def status(self) -> RichText:
        return RichText(self.reading.status_text())
