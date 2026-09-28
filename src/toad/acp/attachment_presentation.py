"""Local observer views, never encoded as ACP facts or used as input authority."""

from dataclasses import dataclass

from agent_comms.acp_extension import QueueItem, QueueProjection

from toad.private_native_cursor import CursorStatus


@dataclass(frozen=True)
class CursorPresentation:
    status: CursorStatus | None


@dataclass(frozen=True)
class QueuePresentation:
    projection: QueueProjection
    starts: tuple[QueueItem, ...] = ()
