"""Native keyed rows over Core's declaration-owned table presentation."""

from __future__ import annotations

from agent_comms.disclosure_text import ViewTable
from textual.content import Content
from textual.style import Style
from textual.widgets import DataTable
from textual.widgets._data_table import RowKey
from ui_theme.scheme import ForegroundColour, ThemeColour

from toad.widget_actions import MovesCursor, OpensSelected
from toad.widgets.declared_disclosure import AnonymousKey, DisclosureKey, DisclosedValue


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
        """A table with a detail pane owns what highlighting a native row does."""

    def preferred_entity(self) -> DisclosureKey:
        """A shared reader may retain its selection when a record moves between tables."""
        return AnonymousKey()

    @property
    def selected_key(self) -> RowKey | None:
        if not self.row_count:
            return None
        return self.coordinate_to_cell_key(self.cursor_coordinate).row_key

    @property
    def selected(self) -> R | None:
        key = self.selected_key
        return None if key is None else self.records.get(key)

    def reconcile_source(self) -> None:
        selected, previous = self.selected_key, self.selected
        offset = self.scroll_offset
        entities = {DisclosedValue.of(record).sequence_key(): record
                    for record in self.source.records}
        if len(entities) != len(self.source.records):
            raise ValueError("A declared table requires unique record identities")
        keys = {entity: self.entity_keys.get(entity, RowKey()) for entity in entities}
        selected = keys.get(self.preferred_entity(), selected)
        incoming = {keys[entity]: record for entity, record in entities.items()}
        rows = []
        for record, texts in zip(incoming.values(), self.source.texts):
            colour = self.app.colours.colour(self.row_tone(record))
            style = Style(background=colour, foreground=colour.get_contrast_text())
            rows.append(tuple(Content(text).stylize(style) for text in texts))
        available = max(len(self.source.columns), self.size.width - self.scrollbar_size_vertical
                        - self.cell_padding * 2 * len(self.source.columns))
        widths = self.source.widths(available)
        columns_changed = tuple((column.key.value, column.width) for column in self.ordered_columns) != tuple(
            (column.name, width) for column, width in zip(self.source.columns, widths)
        )
        same_rows = (tuple(row.key for row in self.ordered_rows) == tuple(incoming)
                     and tuple(tuple(self.get_row(key)) for key in incoming) == tuple(rows))
        self.records, self.entity_keys = incoming, keys
        if same_rows and not columns_changed:
            return
        # Public clear/add owns auto-height remeasurement and native row ordering.
        # Retain row keys, cursor and scroll rather than mutating Textual's caches.
        with self.prevent(DataTable.RowHighlighted):
            self.clear(columns=columns_changed)
            if columns_changed:
                for column, width in zip(self.source.columns, widths):
                    self.add_column(column.label, key=column.name, width=width)
            for key, cells in zip(incoming, rows):
                self.add_row(*cells, key=key, height=None)
            if selected in incoming:
                self.move_cursor(row=self.get_row_index(selected), animate=False, scroll=False)
            elif incoming:
                self.move_cursor(row=min(self.cursor_row, len(incoming) - 1), animate=False, scroll=False)
            self.scroll_to(x=offset.x, y=offset.y, animate=False, force=True)
        if not same_rows and self.selected != previous:
            self.selection_changed()

    def on_resize(self) -> None:
        self.call_after_refresh(self.reconcile_source)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        self.selection_changed()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.selection_changed()

    def cursor_up(self) -> None:
        DataTable.action_cursor_up(self)

    def cursor_down(self) -> None:
        DataTable.action_cursor_down(self)

    def open_selected(self) -> None:
        self.action_select_cursor()
