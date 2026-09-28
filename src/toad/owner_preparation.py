"""Captured read-side service binding for native owner RPC preparation."""

from dataclasses import dataclass, replace

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
    presentation = next((view.presentation for view in comms.views.thread_views()
                         if view.thread.name == name), None)
    return (replace(presentation, notifications=comms.views.recent_notifications(name))
            if presentation is not None else None)
