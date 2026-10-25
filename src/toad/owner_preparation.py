"""Captured read-side service binding for native owner RPC preparation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.comms import Comms
from metaclass_registry.mro_dispatch import handles
from agent_comms.session_load import ExistingSessionLoadPlan
from agent_comms.thread_presentation import (
    LiveThreadOwnerBinding,
    ThreadOwnerBinding,
    ThreadPresentation,
)

from toad.core.projection import MroProjection


class OwnerPlan(ABC):
    """A captured binding either supplies a read-only plan or is unavailable."""

    available: ClassVar[bool] = False

    @abstractmethod
    def require_plan(self) -> ExistingSessionLoadPlan: ...


class UnavailableOwnerPlan(OwnerPlan):
    def require_plan(self) -> ExistingSessionLoadPlan:
        raise ValueError("Read-only attachment requires a live owner binding")


@dataclass(frozen=True)
class AvailableOwnerPlan(OwnerPlan):
    binding: LiveThreadOwnerBinding
    available: ClassVar[bool] = True

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


@dataclass(frozen=True, slots=True)
class OwnerRequestContext:
    """Supply the core proxy's service contract without capturing a UI widget.

    The proxy still resolves and validates the live owner before sending. This
    object supplies only the revision-aware reader, never cached goal/delivery
    state or an alternative authority for request routing.
    """

    _comms: Comms


def read_thread_presentation(comms: Comms, name: str) -> ThreadPresentation:
    """Read the existing core presentation on a worker, without UI dependencies."""
    return comms.views.thread_presentations((name,)).read(name)
