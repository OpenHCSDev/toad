"""Local observer views, never encoded as ACP facts or used as input authority."""

from dataclasses import dataclass

from agent_comms.acp_extension import InputStartedUpdate

from toad.private_native_cursor import CursorStatus


@dataclass(frozen=True)
class CursorPresentation:
    status: type[CursorStatus]

    def matches_turn(self, turn_id: str | None) -> bool:
        return True


@dataclass(frozen=True)
class QueuePresentation:
    starts: tuple[InputStartedUpdate, ...] = ()

    def matches_turn(self, turn_id: str | None) -> bool:
        return True
