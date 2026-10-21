"""Captured read-side service binding for native owner RPC preparation."""

from dataclasses import dataclass

from agent_comms.comms import Comms
from agent_comms.mro_dispatch import handles
from agent_comms.session_load import ExistingSessionLoadPlan
from agent_comms.thread_presentation import (
    LiveThreadOwnerBinding,
    ThreadOwnerBinding,
    ThreadPresentation,
)

from toad.core.projection import MroProjection


class ExistingOwnerPlan(MroProjection):
    """Project Core's binding into a read-only attachment plan without starting an owner."""

    @handles(ThreadOwnerBinding)
    def unavailable(self, binding):
        return None

    @handles(LiveThreadOwnerBinding)
    def live(self, binding):
        return ExistingSessionLoadPlan(binding)

    @classmethod
    def from_binding(
        cls, binding: ThreadOwnerBinding
    ) -> ExistingSessionLoadPlan | None:
        return cls().dispatch_sync(binding)


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
