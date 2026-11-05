"""A Core a UI reads at one root, with the registry and display destinations it serves."""

from __future__ import annotations

from abc import ABC
from pathlib import Path

from agent_comms.core_access import CoreAccess
from agent_comms.display_references import CurrentDisplayReferences
from agent_comms.presentation import WireRevision
from agent_comms.registry_document import RegistrySnapshot
from agent_comms.tools import (CommsReferenceNamesTool, CommsRegistryCutTool, CommsRegistryTool,
                               CommsWireRevisionTool)


class ReferencedCore(ABC):
    """Where this UI's Core requests go and the root that Core serves. An observation and a
    conversation's page source are both one."""

    core: CoreAccess
    root: Path

    def registry(self) -> RegistrySnapshot:
        """Core's thread registry: names, renames and recorded threads resolve against it."""
        return self.core.call(CommsRegistryTool())

    def registry_for(self, *names: str) -> RegistrySnapshot:
        """The registry facts a caller reading ``names`` needs: their rows, aliases, statuses
        and owner generations, beside the fields every thread shares, not every thread's rows."""
        return self.core.call(CommsRegistryCutTool(threads=names))

    def references(self) -> CurrentDisplayReferences:
        """The destinations Core's registry names, keyed by the root it serves."""
        return self.core.call(CommsReferenceNamesTool()).references(str(self.root))

    def wire_revision(self) -> WireRevision:
        """What every wire view at this root derives from."""
        return self.core.call(CommsWireRevisionTool())
