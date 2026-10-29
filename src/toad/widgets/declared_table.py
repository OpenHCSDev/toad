"""Native keyed rows over Core's declaration-owned table presentation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass

from agent_comms.disclosure_text import ViewTable
from textual.content import Content
from textual.style import Style
from textual.widgets import DataTable
from textual.widgets._data_table import RowKey
from ui_theme.scheme import ForegroundColour, ThemeColour

from toad.widget_actions import MovesCursor, OpensSelected
from toad.widgets.declared_disclosure import AnonymousKey, DisclosureKey, DisclosedValue


@dataclass(frozen=True)
class TableSelection[R](ABC):
    """Absent or present original record, never a native row key or a reader request."""

    @property
    @abstractmethod
    def records(self) -> tuple[R, ...]: ...

    @property
    def key(self) -> DisclosureKey:
        return AnonymousKey()

    @classmethod
    def from_records(cls, records: Iterable[R], *preferred: DisclosureKey) -> TableSelection[R]:
        """Resolve semantic preferences against actual records, otherwise take the first."""
        choices = tuple(SelectedTableRecord(record) for record in records)
        empty: TableSelection[R] = EmptyTableSelection()
        return next((choice for key in preferred for choice in choices if choice.key == key),
                    next(iter(choices), empty))


@dataclass(frozen=True)
class EmptyTableSelection[R](TableSelection[R]):
    @property
    def records(self) -> tuple[R, ...]:
        return ()


@dataclass(frozen=True)
class SelectedTableRecord[R](TableSelection[R]):
    record: R

    @property
    def records(self) -> tuple[R, ...]:
        return (self.record,)

    @property
    def key(self) -> DisclosureKey:
        return DisclosedValue.of(self.record).sequence_key()


class DeclaredTable[R](MovesCursor, OpensSelected, DataTable[Content]):
    """Core owns columns and measurement; DataTable owns rows, geometry and repaint."""

    def __init__(self, source: ViewTable[R], **kwargs) -> None:
        super().__init__(cursor_type="row", show_row_labels=False, **kwargs)
        self.source = source
        self.records: dict[RowKey, R] = {}
        self.entity_keys: dict[DisclosureKey, RowKey] = {}
        self.call_after_refresh(self.reconcile_source)

    def present(self, source: ViewTable[R]) -> None:
        self.source = source
        # The native message pump admits this after mount/layout, including updates
        # supplied by a parent's Mount before its child's Mount has run.
        self.call_after_refresh(self.reconcile_source)

    def row_tone(self, record: R) -> type[ThemeColour]:
        return ForegroundColour

    def selection_changed(self) -> None:
        """The actual selected source record changed during reconciliation."""

    def selection_highlighted(self) -> None:
        """Native navigation may intentionally choose a different semantic record."""
        self.selection_changed()

    def preferred_selection(self) -> TableSelection[R]:
        """A shared reader may retain its record when it moves between tables."""
        return self.selected

    @property
    def selected(self) -> TableSelection[R]:
        if not self.row_count:
            return EmptyTableSelection()
        key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
        return SelectedTableRecord(self.records[key])

    def reconcile_source(self) -> None:
        previous = self.selected
        offset = self.scroll_offset
        entities = {DisclosedValue.of(record).sequence_key(): record
                    for record in self.source.records}
        if len(entities) != len(self.source.records):
            raise ValueError("A declared table requires unique record identities")
        selected = TableSelection[R].from_records(
            entities.values(), self.preferred_selection().key, previous.key,
        )
        available = self.size.width - self.scrollbar_size_vertical
        layout = self.source.layout(available - self.cell_padding * 2 * len(self.source.columns))
        widths = layout.widths(max(1, available - self.cell_padding * 2 * len(layout.columns)))
        self.show_header = layout.show_header
        rows = []
        for record, texts in zip(entities.values(), layout.texts):
            colour = self.app.colours.colour(self.row_tone(record))
            style = Style(background=colour, foreground=colour.get_contrast_text())
            rows.append(tuple(Content(text).stylize(style) for text in texts))
        columns_changed = tuple((column.key.value, column.width) for column in self.ordered_columns) != tuple(
            (column.name, width) for column, width in zip(layout.columns, widths)
        )
        same_rows = (tuple(self.entity_keys) == tuple(entities)
                     and tuple(row.key for row in self.ordered_rows) == tuple(self.entity_keys.values())
                     and tuple(tuple(self.get_row(key)) for key in self.entity_keys.values()) == tuple(rows))
        with self.prevent(DataTable.RowHighlighted):
            if same_rows and not columns_changed:
                # The actual record can change while every painted cell stays equal.
                self.records = {self.entity_keys[entity]: record for entity, record in entities.items()}
            else:
                # Anonymous keys are allocated by add_row, never invented beside it.
                # Rebuild both maps from the returned keys, retaining semantic identity.
                self.clear(columns=columns_changed)
                if columns_changed:
                    for column, width in zip(layout.columns, widths):
                        self.add_column(column.label, key=column.name, width=width)
                records: dict[RowKey, R] = {}
                keys: dict[DisclosureKey, RowKey] = {}
                for (entity, record), cells in zip(entities.items(), rows):
                    native = self.add_row(
                        *cells, height=None,
                        key=self.entity_keys[entity].value if entity in self.entity_keys else None,
                    )
                    records[native], keys[entity] = record, native
                self.records, self.entity_keys = records, keys
                self.scroll_to(x=offset.x, y=offset.y, animate=False, force=True)
            for record in selected.records:
                key = self.entity_keys[DisclosedValue.of(record).sequence_key()]
                self.move_cursor(row=self.get_row_index(key), animate=False, scroll=False)
        if self.selected != previous:
            self.selection_changed()

    def on_resize(self) -> None:
        self.call_after_refresh(self.reconcile_source)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        self.selection_highlighted()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.selection_highlighted()

    def cursor_up(self) -> None:
        DataTable.action_cursor_up(self)

    def cursor_down(self) -> None:
        DataTable.action_cursor_down(self)

    def open_selected(self) -> None:
        self.action_select_cursor()
