"""Structural input contracts for a relationship tree.

These are read-only presentation interfaces, not a durable relationship store.
The core adapter or an isolated test fixture supplies the facts.
"""

from typing import Protocol

from agent_comms import ThreadSort, ThreadView


class RelationshipEntry(Protocol):
    target: str
    kind: str
    person: ThreadView | None
    sequence: int
    timestamp: float
    detail: str
    available: bool


class RelationshipGroup(Protocol):
    key: str
    title: str
    entries: tuple[RelationshipEntry, ...]
    order: ThreadSort | None


class ThreadCommsSnapshot(Protocol):
    owner: str
    root: str
    groups: tuple[RelationshipGroup, ...]
    history_limited: bool
    history_messages: int
    incoming_basis: str


class RelationshipSource(Protocol):
    """Synchronous reads run off the UI loop; mutation is an explicit sort action."""

    def revision(self) -> object: ...

    def snapshot(self, owner: str) -> ThreadCommsSnapshot: ...

    def set_order(self, owner: str, group: str, order: ThreadSort) -> ThreadSort: ...
