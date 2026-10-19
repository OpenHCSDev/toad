"""Local observer views, never encoded as ACP facts or used as input authority."""

from dataclasses import dataclass

from agent_comms.acp_extension import InputStartedUpdate

from toad.private_native_cursor import CursorStatus


class AttachmentPresentation:
    """Local attachment observations belong to their session, not a turn."""

    def matches_turn(self, turn_id: object) -> bool:
        return True


@dataclass(frozen=True)
class CursorPresentation(AttachmentPresentation):
    status: type[CursorStatus]


@dataclass(frozen=True)
class QueuePresentation(AttachmentPresentation):
    starts: tuple[InputStartedUpdate, ...] = ()
