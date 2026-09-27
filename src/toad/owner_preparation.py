"""Captured read-side service binding for native owner RPC preparation."""

from dataclasses import dataclass

from agent_comms import Comms


@dataclass(frozen=True, slots=True)
class OwnerRequestContext:
    """Supply the core proxy's service contract without capturing a UI widget.

    The proxy still resolves and validates the live owner before sending. This
    object supplies only the revision-aware reader, never cached goal/delivery
    state or an alternative authority for request routing.
    """

    _comms: Comms
