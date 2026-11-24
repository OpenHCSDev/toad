"""Context reads over a test's own Core, the way an Observing reads it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from agent_comms.comms import Comms
from agent_comms.transport.tool_caller import HumanCaller
from agent_comms.transport.core_access import CoreAccess
from agent_comms.transport.tool_request import ServedRequest, ToolRequest, ToolResult

from toad.client.context_reads import ContextReads


@dataclass(frozen=True)
class DirectCoreAccess(CoreAccess):
    """In-process CoreAccess for tests without spawning an ObservationProcess child."""

    comms: Comms

    def call[R: ToolResult](self, request: ToolRequest[R]) -> R:
        return cast(R, ServedRequest.serving(request).apply_without_thread(self.comms, HumanCaller()))


@dataclass(frozen=True)
class LocalContextReads(ContextReads):
    """The fixture's Core, read the way an Observing reads it, without an observation process."""

    service: Comms

    @property
    def core(self) -> CoreAccess:
        return DirectCoreAccess(self.service)

    @property
    def root(self) -> Path:
        return self.service.root
