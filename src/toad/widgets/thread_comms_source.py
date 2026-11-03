"""A thread sidebar's relationships, read from and ordered through Core."""

from dataclasses import dataclass

from agent_comms.core_access import CoreAccess
from agent_comms.display_order import ThreadSort
from agent_comms.presentation import WireRevision
from agent_comms.relationships import SortableRelationshipGroup, ThreadCommsSnapshot
from agent_comms.tools import (
    CommsRelationshipRevisionTool, CommsSetRelationshipOrderTool, CommsThreadRelationshipsTool,
)


@dataclass(frozen=True)
class CoreRelationships:
    """The relationship reads a sidebar makes, locally or across the connector alike."""

    core: CoreAccess

    def revision(self) -> WireRevision:
        return self.core.call(CommsRelationshipRevisionTool()).revision

    def snapshot(self, owner: str) -> ThreadCommsSnapshot:
        return self.core.call(CommsThreadRelationshipsTool(owner=owner)).snapshot

    def set_order(self, owner: str, group: type[SortableRelationshipGroup],
                  order: type[ThreadSort]) -> type[ThreadSort]:
        return self.core.call(CommsSetRelationshipOrderTool(owner=owner, group=group, order=order)).order
