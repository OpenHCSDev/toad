"""Thin binding from the core relationship service to its UI source protocol."""

from functools import cached_property
from pathlib import Path

from agent_comms import Comms, ThreadSort, wire


class WireRelationshipSource:
    def __init__(self, root: str, shared: Comms):
        self.root = Path(root).expanduser().resolve()
        self.shared = shared

    @cached_property
    def service(self):
        # Called by the widget's background read, never during composition.
        comms = self.shared if self.shared.root.resolve() == self.root else wire(self.root)
        return comms.relationships

    def revision(self):
        return self.service.revision()

    def snapshot(self, owner: str):
        return self.service.snapshot(owner)

    def set_order(self, owner: str, group: str, order: ThreadSort) -> ThreadSort:
        return self.service.set_order(owner, group, order)
