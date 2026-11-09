"""Lazy native paint over Core's prepared disclosure tree."""

from __future__ import annotations

from agent_comms.disclosure_text import DisclosureEntry, DisclosureKey, DisclosureText, StructuredText
from metaclass_registry.mro_dispatch import MroDispatch, handles
from textual import events
from textual.containers import VerticalGroup
from textual.content import Content
from textual.widgets import Collapsible, Static

from toad.native_style import AutoHeight, Borderless, NoMargin, NoPadding
from textual import on

from toad.keyed_rows import KeyedRows


class DisclosureContents(AutoHeight, Collapsible.Contents):
    """A disclosure's members indent under its title without Collapsible's gap."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (0, 0, 0, 2)


class DeclaredDisclosure(
    KeyedRows[DisclosureKey],
    MroDispatch,
    Borderless,
    AutoHeight,
    NoPadding,
    NoMargin,
    Collapsible,
):
    """Core owns children and identity; native widgets own expansion and focus."""

    Contents = DisclosureContents

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        # Collapsible constructs its title itself; the disclosure owns its one-line form.
        title = self._title.styles
        title.height = 1
        title.padding = 0
        title.text_wrap = "nowrap"
        title.text_overflow = "ellipsis"

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

    @on(events.Resize)
    def on_resize(self, event: events.Resize) -> None:
        self.fit_title()

    def present(self, entry: DisclosureEntry) -> None:
        self.entry = entry
        self.fit_title()
        if self.is_mounted and not self.collapsed:
            self.show_source()

    @on(Collapsible.Expanded)
    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self:
            event.stop()
            self.show_source()
