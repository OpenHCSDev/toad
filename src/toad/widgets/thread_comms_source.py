"""The Core relationship service's UI source protocol."""

from typing import Protocol
from agent_comms.display_order import ThreadSort
from agent_comms.relationships import SortableRelationshipGroup, ThreadCommsSnapshot


class RelationshipSource(Protocol):
    """The root-bound service is acquired off the UI loop by its read owner."""

    def revision(self) -> object: ...

    def snapshot(self, owner: str) -> ThreadCommsSnapshot: ...

    def set_order(self, owner: str, group: type[SortableRelationshipGroup],
                  order: type[ThreadSort]) -> type[ThreadSort]: ...
