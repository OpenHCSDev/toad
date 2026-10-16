"""Thin binding from the core relationship service to its UI source protocol."""

from functools import cached_property
from pathlib import Path
from typing import Protocol

from agent_comms.comms import Comms, wire
from agent_comms.display_order import ThreadSort
from agent_comms.relationships import SortableRelationshipGroup, ThreadCommsSnapshot


class RelationshipSource(Protocol):
    """The root-bound service is acquired off the UI loop by its read owner."""

    def revision(self) -> object: ...

    def snapshot(self, owner: str) -> ThreadCommsSnapshot: ...

    def set_order(self, owner: str, group: type[SortableRelationshipGroup],
                  order: type[ThreadSort]) -> type[ThreadSort]: ...


class WireRelationshipSource:
    def __init__(self, root: str, shared: Comms | None):
        self.root = Path(root).expanduser().resolve()
        self.shared = shared

    @cached_property
    def service(self):
        # Called by the widget's background read, never during composition.
        comms = (self.shared if self.shared is not None and self.shared.root.resolve() == self.root
                 else wire(self.root))
        return comms.relationships

    def revision(self):
        return self.service.revision()

    def snapshot(self, owner: str):
        return self.service.snapshot(owner)

    def set_order(self, owner: str, group: type[SortableRelationshipGroup], order: type[ThreadSort]) -> type[ThreadSort]:
        return self.service.set_order(owner, group, order)
