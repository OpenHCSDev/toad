"""A Core a UI reads, with the display destinations its registry resolves."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent_comms.core_access import CoreAccess
from agent_comms.display_references import CurrentDisplayReferences


class ReferencedCore(ABC):
    """Where this UI's Core requests go, and the destinations that Core's registry names.
    An observation and a conversation's page source are both one."""

    core: CoreAccess

    @abstractmethod
    def references(self) -> CurrentDisplayReferences: ...
