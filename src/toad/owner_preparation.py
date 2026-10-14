"""Captured read-side service binding for native owner RPC preparation."""

from dataclasses import dataclass

from agent_comms.comms import Comms
from agent_comms.thread_presentation import ThreadPresentation, ThreadOwnerBinding, LiveThreadOwnerBinding
from agent_comms.session_load import ExistingSessionLoadAdmission
from agent_comms.mro_dispatch import handles
from toad.core.projection import MroProjection


class ExistingOwnerAdmission(MroProjection):
    """Project Core's binding into read-only attachment admission, without starting an owner."""

    @handles(ThreadOwnerBinding)
    def unavailable(self, binding):
        return None

    @handles(LiveThreadOwnerBinding)
    def live(self, binding):
        return ExistingSessionLoadAdmission(binding)

    @classmethod
    def from_binding(cls, binding: ThreadOwnerBinding) -> ExistingSessionLoadAdmission | None:
        return cls().dispatch_sync(binding)


@dataclass(frozen=True, slots=True)
class OwnerRequestContext:
    """Supply the core proxy's service contract without capturing a UI widget.

    The proxy still resolves and validates the live owner before sending. This
    object supplies only the revision-aware reader, never cached goal/delivery
    state or an alternative authority for request routing.
    """

    _comms: Comms


def read_thread_presentation(comms: Comms, name: str) -> ThreadPresentation | None:
    """Read the existing core presentation on a worker, without UI dependencies."""
    return comms.views.thread_presentation(name)
