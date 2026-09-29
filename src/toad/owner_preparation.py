"""Captured read-side service binding for native owner RPC preparation."""

from dataclasses import dataclass

from agent_comms.comms import Comms
from agent_comms.thread_presentation import ThreadPresentation


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
