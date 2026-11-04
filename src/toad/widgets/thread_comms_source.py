"""A thread sidebar's relationship reads: a capability of anything that holds a Core."""

from agent_comms.core_access import CoreAccess
from agent_comms.display_order import ThreadSort
from agent_comms.relationships import SortableRelationshipGroup, ThreadCommsSnapshot
from agent_comms.tools import (
    CommsSetRelationshipOrderTool, CommsThreadRelationshipsTool,
)


class RelationshipReads:
    """Relationship reads and ordering through this holder's Core, locally or remotely alike."""

    core: CoreAccess

    def relationships(self, owner: str) -> ThreadCommsSnapshot:
        return self.core.call(CommsThreadRelationshipsTool(owner=owner))

    def set_relationship_order(self, owner: str, group: type[SortableRelationshipGroup],
                               order: type[ThreadSort]) -> type[ThreadSort]:
        return self.core.call(CommsSetRelationshipOrderTool(owner=owner, group=group, order=order)).order
