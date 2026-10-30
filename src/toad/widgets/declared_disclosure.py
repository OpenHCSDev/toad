"""Lazy native paint over Core's prepared disclosure tree."""

from __future__ import annotations

from agent_comms.disclosure_text import DisclosureEntry, DisclosureKey, DisclosureText, StructuredText
from metaclass_registry.mro_dispatch import MroDispatch, handles
from textual import events
from textual.containers import VerticalGroup
from textual.content import Content
from textual.widgets import Collapsible, Static

from toad.widgets.sidebar_tree import KeyedRows


class DeclaredDisclosure(KeyedRows[DisclosureKey], MroDispatch, Collapsible):
    """Core owns children and identity; native widgets own expansion and focus."""

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
        # Reconciliation borrows the immediate prepared children only for this call.
        by_key = {entry.key: entry for entry in entries}
        if len(by_key) != len(entries):
            raise ValueError(f"Repeated declared identity in {self.entry.label}")
        self.pending_entries = by_key
        try:
            self.reconcile_keys(tuple(self.pending_entries), changed=frozenset(self.pending_entries))
        finally:
            del self.pending_entries

    @handles(DisclosureText)
    def scalar(self, source: DisclosureText) -> None:
        self.body.display = True
        self.members.display = False
        self.body.update(source.summary)

    @handles(StructuredText)
    def structured(self, source: StructuredText) -> None:
        self.body.display = False
        self.members.display = True
        self.reconcile_entries(source.children)

    def show_source(self) -> None:
        source = self.entry.value
        type(self).handler_for(type(source))(self, source)

    def fit_title(self) -> None:
        width = max(1, self.size.width - 2)
        title = Content(f"{self.entry.label}: {self.entry.value.summary}".partition("\n")[0])
        self.title = title.truncate(width, ellipsis=True)

    def on_resize(self, event: events.Resize) -> None:
        self.fit_title()

    def present(self, entry: DisclosureEntry) -> None:
        self.entry = entry
        self.fit_title()
        if self.is_mounted and not self.collapsed:
            self.show_source()

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self:
            event.stop()
            self.show_source()
