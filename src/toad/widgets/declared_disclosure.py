"""Lazy disclosures of declared values, not a second handwritten record schema."""

from __future__ import annotations

from dataclasses import dataclass
from functools import singledispatchmethod
from typing import Hashable

from agent_comms.disclosure_text import (
    ClassText, DisclosureText, FamilyText, IdentifiedRecordText,
    MappingText, RecordText, SequenceText,
)
from agent_comms.field_codec import FieldCodec
from python_introspect import declared_field_label
from textual import events
from textual.containers import VerticalGroup
from textual.content import Content
from textual.widgets import Collapsible, Static

from toad.widgets.sidebar_tree import KeyedRows


class DisclosureKey:
    """Nominal native-row identity; its members carry only their differing components."""


@dataclass(frozen=True)
class RecordKey(DisclosureKey):
    owner: type


class RootKey(RecordKey):
    """The whole record, not one of its fields."""


@dataclass(frozen=True)
class FieldKey(RecordKey):
    name: str


@dataclass(frozen=True)
class EntityKey(RecordKey):
    parts: tuple[object, ...]


class AnonymousKey(DisclosureKey):
    """A source without declared entity identity cannot inherit another item's view."""


@dataclass(frozen=True)
class MappingKey(DisclosureKey):
    key: Hashable


@dataclass(frozen=True)
class DisclosedValue:
    """One borrowed value. Shape is recovered only at this structural boundary."""

    source: DisclosureText

    @property
    def value(self) -> object:
        return self.source.value

    @classmethod
    def of(cls, value: object) -> DisclosedValue:
        return cls.from_text(DisclosureText.of(value))

    @singledispatchmethod
    @classmethod
    def from_text(cls, source: DisclosureText) -> DisclosedValue:
        """Adapt Core's decoded shape; never rediscover the original value's shape."""
        return cls(source)

    @from_text.register(ClassText)
    @classmethod
    def _class(cls, source: ClassText) -> DisclosedValue:
        return ClassValue(source)

    @from_text.register(FamilyText)
    @classmethod
    def _family_class(cls, source: FamilyText) -> DisclosedValue:
        return FamilyClassValue(source)

    @from_text.register(RecordText)
    @classmethod
    def _record(cls, source: RecordText) -> DisclosedValue:
        return RecordValue(source)

    @from_text.register(IdentifiedRecordText)
    @classmethod
    def _identified(cls, source: IdentifiedRecordText) -> DisclosedValue:
        return IdentifiedRecordValue(source)

    @from_text.register(MappingText)
    @classmethod
    def _mapping(cls, source: MappingText) -> DisclosedValue:
        return MappingValue(source)

    @from_text.register(SequenceText)
    @classmethod
    def _sequence(cls, source: SequenceText) -> DisclosedValue:
        return SequenceValue(source)

    def sequence_key(self) -> DisclosureKey:
        return AnonymousKey()

    def identity_part(self) -> object:
        return self.value

    def summary(self, width: int | None = None) -> str:
        return self.source.summary(width)

    def cell(self) -> Content:
        return Content(str(self.value))

    def show(self, view: DeclaredDisclosure) -> None:
        view.body.display = True
        view.members.display = False
        view.body.update(str(self.value))


@dataclass(frozen=True)
class ClassValue(DisclosedValue):
    source: ClassText

    def cell(self) -> Content:
        return Content(self.summary())

    def show(self, view: DeclaredDisclosure) -> None:
        view.body.display = True
        view.members.display = False
        view.body.update(self.summary())


@dataclass(frozen=True)
class FamilyClassValue(ClassValue):
    source: FamilyText


class StructuredValue(DisclosedValue):
    def cell(self) -> Content:
        return Content(self.summary())

    def children(self) -> tuple[DisclosureEntry, ...]:
        raise NotImplementedError

    def show(self, view: DeclaredDisclosure) -> None:
        view.body.display = False
        view.members.display = True
        entries = self.children()
        view.reconcile_entries(entries)


class RecordValue(StructuredValue):
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
class IdentifiedRecordValue(RecordValue):
    source: IdentifiedRecordText

    def sequence_key(self) -> EntityKey:
        return EntityKey(type(self.value), tuple(
            DisclosedValue.of(plan.current(self.value)).identity_part()
            for plan in self.source.identity
        ))

    def identity_part(self) -> EntityKey:
        return self.sequence_key()


@dataclass(frozen=True)
class SequenceValue(StructuredValue):
    source: SequenceText

    def children(self) -> tuple[DisclosureEntry, ...]:
        entries = []
        for index, value in enumerate(self.source.value):
            disclosed = DisclosedValue.of(value)
            entries.append(DisclosureEntry(disclosed.sequence_key(), str(index + 1), disclosed))
        return tuple(entries)


@dataclass(frozen=True)
class MappingValue(StructuredValue):
    source: MappingText

    def children(self) -> tuple[DisclosureEntry, ...]:
        return tuple(
            DisclosureEntry(MappingKey(key), str(key), DisclosedValue.of(value))
            for key, value in self.source.value.items()
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
        by_key = {entry.key: entry for entry in entries}
        if len(by_key) != len(entries):
            raise ValueError(f"Repeated declared identity in {self.entry.label}")
        self.pending_entries = by_key
        try:
            self.reconcile_keys(tuple(self.pending_entries), changed=frozenset(self.pending_entries))
        finally:
            del self.pending_entries

    def fit_title(self) -> None:
        width = max(1, self.size.width - 2)
        title = Content(f"{self.entry.label[:width]}: {self.entry.value.summary(width)}")
        self.title = title.truncate(width, ellipsis=True)

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
