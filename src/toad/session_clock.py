"""When the agent session started, as the end-of-session usage report reads it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from toad.launch_binding import AgentBinding


class SessionClock:
    """A session that never started reports no end; a started one reports its duration."""

    def report_end(
        self, launch: AgentBinding, publish: Callable[..., object], **fields: object
    ) -> None:
        """Nothing ran, so nothing ended."""


@dataclass(frozen=True)
class NotStarted(SessionClock):
    """The agent has not answered ready in this conversation."""


@dataclass(frozen=True)
class StartedAt(SessionClock):
    started: float

    def report_end(
        self, launch: AgentBinding, publish: Callable[..., object], **fields: object
    ) -> None:
        launch.publish_usage(
            publish, "agent-session-end", duration=monotonic() - self.started, **fields
        )
