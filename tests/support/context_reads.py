"""Context reads over a test's own Core, the way an Observing reads it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.core_access import LocalCoreAccess

from toad.core.context_reads import ContextReads


@dataclass(frozen=True)
class LocalContextReads(ContextReads):
    """The fixture's Core, read the way an Observing reads it, without an observation process."""

    service: Comms

    @property
    def core(self) -> LocalCoreAccess:
        return LocalCoreAccess(self.service)

    @property
    def root(self) -> Path:
        return self.service.root
