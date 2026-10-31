"""Native keyed rows over Core's declaration-owned table presentation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_comms.disclosure_text import AnonymousKey, DisclosureKey, ViewTable
from textual.content import Content
from textual.style import Style
from textual.widgets import DataTable
from textual.widgets._data_table import RowKey
from ui_theme.scheme import ForegroundColour, ThemeColour

from toad.widget_actions import OpensSelected


class SelectionView[R]:
    """A native selection consumer implements both states without another wrapper."""

    @abstractmethod
    def clear_selection(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def show_selection(self, key: DisclosureKey, record: R) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class TableSelection[R](ABC):
    """Own empty/selected presentation dispatch, never transport or reader work."""

    @property
    def key(self) -> DisclosureKey:
        return AnonymousKey()

    @abstractmethod
    def present_to(self, view: SelectionView[R]) -> None: ...

    def place_cursor(self, table: DeclaredTable[R]) -> None:
        """An empty selection has no native cursor to place."""

    @classmethod
    def from_records(cls, records: Mapping[DisclosureKey, R],
                     *preferred: DisclosureKey) -> TableSelection[R]:
        """Use already derived identities, otherwise choose the first actual record."""
        for key in preferred:
            if key in records:
                return SelectedTableRecord(key, records[key])
        for key, record in records.items():
            return SelectedTableRecord(key, record)
        return EmptyTableSelection()


@dataclass(frozen=True)
class EmptyTableSelection[R](TableSelection[R]):
    def present_to(self, view: SelectionView[R]) -> None:
        view.clear_selection()


@dataclass(frozen=True, slots=True)
class SelectedTableRecord[R](TableSelection[R]):
    key: DisclosureKey = field()
    record: R

    def present_to(self, view: SelectionView[R]) -> None:
        view.show_selection(self.key, self.record)

    def place_cursor(self, table: DeclaredTable[R]) -> None:
        native = table.entity_keys[self.key]
        table.move_cursor(row=table.get_row_index(native), animate=False, scroll=False)


class DeclaredTable[R](OpensSelected, DataTable[Content]):
    """Core owns columns and measurement; DataTable owns rows, geometry and repaint."""

    def __init__(self, source: ViewTable[R]) -> None:
        super().__init__(cursor_type="row", show_row_labels=False)
        self.records: dict[RowKey, SelectedTableRecord[R]] = {}
        self.entity_keys: dict[DisclosureKey, RowKey] = {}
        self.present(source)

    def present(self, source: ViewTable[R]) -> None:
        self.source = source
        # The native message pump runs this after mount/layout, including updates
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
        return self.records[key]

    def reconcile_source(self) -> None:
        previous = self.selected
        offset = self.scroll_offset
        entities = self.source.entities
        selected = TableSelection[R].from_records(
            entities, self.preferred_selection().key, previous.key,
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
                self.records = {self.entity_keys[entity]: SelectedTableRecord(entity, record)
                                for entity, record in entities.items()}
            else:
                # Fresh anonymous keys come from add_row; entity_keys retains the
                # semantic identity that restores selection after the native rebuild.
                self.clear(columns=columns_changed)
                if columns_changed:
                    for column, width in zip(layout.columns, widths):
                        self.add_column(column.label, key=column.name, width=width)
                records: dict[RowKey, SelectedTableRecord[R]] = {}
                keys: dict[DisclosureKey, RowKey] = {}
                for (entity, record), cells in zip(entities.items(), rows):
                    native = self.add_row(*cells, height=None)
                    records[native], keys[entity] = SelectedTableRecord(entity, record), native
                self.records, self.entity_keys = records, keys
                self.scroll_to(x=offset.x, y=offset.y, animate=False, force=True)
            selected.place_cursor(self)
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
