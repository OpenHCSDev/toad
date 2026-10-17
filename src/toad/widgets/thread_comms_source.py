"""Thin binding from the core relationship service to its UI source protocol."""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from textual.content import Content
from agent_comms.presentation import ThreadView
from agent_comms.ui_model.sidebar import PersonUnread, ThreadRowModel
from agent_comms.ui_model.unread import UnobservedUnread

from agent_comms.comms import Comms, wire
from agent_comms.display_order import ThreadSort
from agent_comms.relationships import RelationshipEntry, RelationshipGroup, SortableRelationshipGroup


@dataclass(frozen=True)
class ThreadRowView:
    person: ThreadView
    model: ThreadRowModel

    @cached_property
    def width(self):
        return max(Content(self.model.label).cell_length, Content(self.model.summary).cell_length)

    @classmethod
    def of(cls, person, snapshot, previous):
        unread = (UnobservedUnread() if snapshot is None else
                  person.thread.execution.prepare_conversation(PersonUnread(person, snapshot)))
        return (previous if previous is not None and previous.person == person and previous.model.unread == unread
                else cls(person, ThreadRowModel.of(person, snapshot)))


@dataclass(frozen=True)
class EntryView:
    model: RelationshipEntry

    @cached_property
    def width(self):
        return max((Content(line).cell_length for text in (self.model.target, self.model.detail)
                    for line in text.splitlines()), default=0)


@dataclass(frozen=True)
class GroupView:
    model: RelationshipGroup
    entries: tuple[EntryView, ...]

    @classmethod
    def of(cls, model, previous):
        entries = {view.model.identity: view for view in previous.entries} if previous is not None else {}
        return cls(model, tuple(entries[entry.identity] if entry.identity in entries and entries[entry.identity].model == entry
                               else EntryView(entry) for entry in model.entries))

    @cached_property
    def width(self):
        return max((entry.width for entry in self.entries), default=0)


class RelationshipSource:
    """The typed panel binding owns whether it can begin a relationship read."""
    message = "Relationship source not connected"

    @classmethod
    def for_panel(cls, owner, root, source):
        if not owner or not root:
            return WaitingRelationshipIdentity()
        return source if source is not None else cls()

    def require_service(self):
        raise ValueError(self.message)

    def refresh(self, panel):
        panel.present_context(self.message)


class WaitingRelationshipIdentity(RelationshipSource):
    message = "Waiting for thread identity"


class WireRelationshipSource(RelationshipSource):
    def __init__(self, root: str, shared: Comms | None):
        self.root = Path(root).expanduser().resolve()
        self.shared = shared

    @cached_property
    def service(self):
        # Called by the widget's background read, never during composition.
        comms = (self.shared if self.shared is not None and self.shared.root.resolve() == self.root
                 else wire(self.root))
        return comms.relationships

    def require_service(self):
        return self

    def refresh(self, panel):
        panel.start_refresh()

    def revision(self):
        return self.service.revision()

    def snapshot(self, owner: str):
        return self.service.snapshot(owner)

    def set_order(self, owner: str, group: type[SortableRelationshipGroup], order: type[ThreadSort]) -> type[ThreadSort]:
        return self.service.set_order(owner, group, order)
