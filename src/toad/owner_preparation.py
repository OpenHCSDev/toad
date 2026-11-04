"""Core's captured binding supplies a read-only native owner plan."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from metaclass_registry.mro_dispatch import handles
from agent_comms.session_load import ExistingSessionLoadPlan
from agent_comms.thread_presentation import (
    LiveThreadOwnerBinding,
    ThreadOwnerBinding,
)

from toad.core.projection import MroProjection
from toad.input_decision import InputAccepted, InputDecision, OwnerNotAttached


class OwnerPlan(ABC):
    """A captured binding either supplies a read-only plan or is unavailable."""

    decision: ClassVar[InputDecision]

    @property
    def available(self) -> bool:
        return self.decision.allows

    @abstractmethod
    def require_plan(self) -> ExistingSessionLoadPlan: ...


class UnavailableOwnerPlan(OwnerPlan):
    decision: ClassVar[OwnerNotAttached] = OwnerNotAttached()

    def require_plan(self) -> ExistingSessionLoadPlan:
        raise ValueError(self.decision.message)


@dataclass(frozen=True)
class AvailableOwnerPlan(OwnerPlan):
    binding: LiveThreadOwnerBinding
    decision: ClassVar[InputAccepted] = InputAccepted()

    def require_plan(self) -> ExistingSessionLoadPlan:
        return ExistingSessionLoadPlan(self.binding)


class ExistingOwnerPlan(MroProjection[OwnerPlan]):
    """Project Core's binding into a read-only attachment plan without starting an owner."""

    @handles(ThreadOwnerBinding)
    def unavailable(self, binding: ThreadOwnerBinding) -> OwnerPlan:
        return UnavailableOwnerPlan()

    @handles(LiveThreadOwnerBinding)
    def live(self, binding: LiveThreadOwnerBinding) -> OwnerPlan:
        return AvailableOwnerPlan(binding)

    @classmethod
    def from_binding(cls, binding: ThreadOwnerBinding) -> OwnerPlan:
        return cls().project_value(binding)
