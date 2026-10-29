"""Lazy disclosures of declared values, not a second handwritten record schema."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, is_dataclass
from typing import Hashable

from agent_comms.field_codec import FieldCodec
from python_introspect import declared_field_label
from textual import events
from textual.containers import VerticalGroup
from textual.content import Content
from textual.widgets import Collapsible, Static

from toad.widgets.sidebar_tree import KeyedRows


@dataclass(frozen=True)
class FieldKey:
    owner: type
    name: str


@dataclass(frozen=True)
class ItemKey:
    position: int


@dataclass(frozen=True)
class MappingKey:
    key: Hashable


type DisclosureKey = FieldKey | ItemKey | MappingKey


@dataclass(frozen=True)
class DisclosedValue:
    """One borrowed value. Shape is recovered only at this structural boundary."""

    value: object

    @classmethod
    def of(cls, value: object) -> DisclosedValue:
        if is_dataclass(value) and not isinstance(value, type):
            return RecordValue(value)
        if isinstance(value, Mapping):
            return MappingValue(value)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return SequenceValue(value)
        return cls(value)

    @property
    def summary(self) -> str:
        return str(self.value).partition("\n")[0]

    def show(self, view: DeclaredDisclosure) -> None:
        view.body.display = True
        view.members.display = False
        view.body.update(str(self.value))


class StructuredValue(DisclosedValue):
    def children(self) -> tuple[DisclosureEntry, ...]:
        raise NotImplementedError

    def show(self, view: DeclaredDisclosure) -> None:
        view.body.display = False
        view.members.display = True
        entries = self.children()
        view.reconcile_entries(entries)


class RecordValue(StructuredValue):
    @property
    def summary(self) -> str:
        return type(self.value).__name__

    def children(self) -> tuple[DisclosureEntry, ...]:
        return tuple(
            DisclosureEntry(
                FieldKey(type(self.value), plan.name),
                declared_field_label(plan.annotation) or plan.key.replace("_", " ").capitalize(),
                DisclosedValue.of(plan.current(self.value)),
            )
            for plan in FieldCodec.field_plans(type(self.value)) if plan.records
        )


@dataclass(frozen=True)
class SequenceValue(StructuredValue):
    value: Sequence

    @property
    def summary(self) -> str:
        return f"{len(self.value)} items"

    def children(self) -> tuple[DisclosureEntry, ...]:
        return tuple(
            DisclosureEntry(ItemKey(index), str(index + 1), DisclosedValue.of(value))
            for index, value in enumerate(self.value)
        )


@dataclass(frozen=True)
class MappingValue(StructuredValue):
    value: Mapping

    @property
    def summary(self) -> str:
        return f"{len(self.value)} fields"

    def children(self) -> tuple[DisclosureEntry, ...]:
        return tuple(
            DisclosureEntry(MappingKey(key), str(key), DisclosedValue.of(value))
            for key, value in self.value.items()
        )


@dataclass(frozen=True)
class DisclosureEntry:
    key: DisclosureKey
    label: str
    value: DisclosedValue


class DeclaredDisclosure(KeyedRows[DisclosureKey], Collapsible):
    """Native widgets own expansion/focus; only open branches acquire child widgets."""

    DEFAULT_CSS = """
    DeclaredDisclosure { height: auto; border: none; padding: 0; margin: 0; }
    DeclaredDisclosure > CollapsibleTitle { height: 1; padding: 0; text-wrap: nowrap; text-overflow: ellipsis; }
    DeclaredDisclosure > Contents { height: auto; padding: 0 0 0 2; }
    DeclaredDisclosure Static { height: auto; }
    """

    def __init__(self, entry: DisclosureEntry) -> None:
        self.entry = entry
        self.body = Static("", markup=False)
        self.body.display = False
        self.members = VerticalGroup()
        super().__init__(self.body, self.members, title="", collapsed=True)
        self.present(entry)

    @property
    def member_container(self) -> VerticalGroup:
        return self.members

    @property
    def rows(self) -> dict[DisclosureKey, DeclaredDisclosure]:
        return {row.entry.key: row for row in self.members.query_children(DeclaredDisclosure)}

    def create_row(self, key: DisclosureKey) -> DeclaredDisclosure:
        return DeclaredDisclosure(self.pending_entries[key])

    def update_row(self, key: DisclosureKey, row: DeclaredDisclosure) -> None:
        row.present(self.pending_entries[key])

    def reconcile_entries(self, entries: tuple[DisclosureEntry, ...]) -> None:
        # Reconciliation borrows the immediate declarations only for this call.
        self.pending_entries = {entry.key: entry for entry in entries}
        try:
            self.reconcile_keys(tuple(self.pending_entries), changed=frozenset(self.pending_entries))
        finally:
            del self.pending_entries

    def fit_title(self) -> None:
        title = Content(f"{self.entry.label}: {self.entry.value.summary}")
        self.title = title.truncate(max(1, self.size.width - 2), ellipsis=True)

    def on_resize(self, event: events.Resize) -> None:
        self.fit_title()

    def present(self, entry: DisclosureEntry) -> None:
        self.entry = entry
        self.fit_title()
        if self.is_mounted and not self.collapsed:
            entry.value.show(self)

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self:
            event.stop()
            self.entry.value.show(self)
