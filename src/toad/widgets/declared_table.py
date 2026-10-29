"""A keyed table whose columns and cells come from record declarations."""

from __future__ import annotations

from collections.abc import Iterable

from agent_comms.field_codec import FieldCodec, ViewColumn
from rich.cells import cell_len
from textual.style import Style
from textual._two_way_dict import TwoWayDict
from textual.content import Content
from textual.widgets import DataTable
from textual.widgets._data_table import RowKey
from ui_theme.scheme import ForegroundColour, ThemeColour

from toad.widget_actions import MovesCursor, OpensSelected
from toad.widgets.declared_disclosure import DisclosureKey, DisclosedValue


class DeclaredTable[R](MovesCursor, OpensSelected, DataTable[Content]):
    """Keep native rows and cursor identity while the source replaces its records."""

    record: type[R]
    view: str

    def __init_subclass__(cls, *, record: type[R], view: str, **kwargs) -> None:
        cls.record = record
        cls.view = view
        super().__init_subclass__(**kwargs)

    def __init__(self, **kwargs) -> None:
        super().__init__(cursor_type="row", show_row_labels=False, **kwargs)
        self.column_plans = FieldCodec.view_columns(self.record, self.view)
        self.records: dict[RowKey, R] = {}
        self.entity_keys: dict[DisclosureKey, RowKey] = {}

    def on_mount(self) -> None:
        for column in self.column_plans:
            self.add_column(column.label, key=column.name)
        self.present(tuple(self.records.values()))

    def row_tone(self, record: R) -> type[ThemeColour]:
        return ForegroundColour

    def cells(self, record: R) -> tuple[Content, ...]:
        return tuple(DisclosedValue.of(column.current(record)).cell() for column in self.column_plans)

    @property
    def selected_key(self) -> RowKey | None:
        if not self.row_count:
            return None
        return self.coordinate_to_cell_key(self.cursor_coordinate).row_key

    @property
    def selected(self) -> R | None:
        return self.records.get(self.selected_key)

    def present(self, records: Iterable[R]) -> None:
        selected = self.selected_key
        entities = {DisclosedValue.of(record).sequence_key(): record for record in records}
        keys = {entity: self.entity_keys.get(entity, RowKey()) for entity in entities}
        incoming = {keys[entity]: record for entity, record in entities.items()}
        # A parent's Mount can supply the frame before this table's Mount creates columns.
        # Keep the supplied records; the table's own column owner admits their native rows.
        if not self.columns:
            self.records, self.entity_keys = incoming, keys
            return
        for key in self.records.keys() - incoming.keys():
            self.remove_row(key)
        changed: set[RowKey] = set()
        for key, record in incoming.items():
            if key in self.rows and self.records[key] == record:
                continue
            colour = self.app.colours.colour(self.row_tone(record))
            style = Style(background=colour, foreground=colour.get_contrast_text())
            cells = tuple(cell.stylize(style) for cell in self.cells(record))
            if key in self.rows:
                for column, cell in zip(self.column_plans, cells):
                    self.update_cell(key, column.name, cell)
            else:
                self.add_row(*cells, key=key, height=None)
            changed.add(key)
        self.records = incoming
        self.entity_keys = keys
        # DataTable has no public keyed reorder. Its own sort() uses this same index;
        # retain Core's supplied order without inventing another state sort in the UI.
        self._row_locations = TwoWayDict({key: index for index, key in enumerate(incoming)})
        self._update_count += 1
        self.reflow_rows(changed)
        self.fit_columns()
        if selected in incoming:
            self.move_cursor(row=self.get_row_index(selected), animate=False)
        elif incoming:
            self.move_cursor(row=min(self.cursor_row, len(incoming) - 1), animate=False)

    def fit_columns(self) -> None:
        columns = self.ordered_columns
        if not columns:
            return
        weights = []
        for column in columns:
            weight = max((cell_len(line)
                          for cell in self.get_column(column.key)
                          for line in cell.plain.splitlines()), default=0)
            column.content_width = max(cell_len(column.label.plain), weight)
            weights.append(max(1, column.content_width))
        available = max(len(columns), self.size.width - self.scrollbar_size_vertical
                        - self.cell_padding * 2 * len(columns))
        minimums = tuple(plan.minimum_width(cell.plain for cell in self.get_column(column.key))
                         for plan, column in zip(self.column_plans, columns))
        widths = ViewColumn.fit_widths(weights, available, minimums)
        if widths == tuple(column.width for column in columns) and not any(
            column.auto_width for column in columns
        ):
            return
        for column, width in zip(columns, widths):
            column.auto_width = False
            column.width = width
        self.reflow_rows(self.rows)

    def reflow_rows(self, keys: Iterable[RowKey]) -> None:
        # Re-measure native auto-height only after cell text or column widths change.
        # A height-only Resize must not zero the rows again: that feeds its own layout.
        for key in keys:
            self.rows[key].height = 0
            self._new_rows.add(key)
        self._require_update_dimensions = True
        self._update_count += 1
        self._clear_caches()
        self.refresh(layout=True)

    def on_resize(self) -> None:
        self.fit_columns()

    def cursor_up(self) -> None:
        DataTable.action_cursor_up(self)

    def cursor_down(self) -> None:
        DataTable.action_cursor_down(self)

    def open_selected(self) -> None:
        self.action_select_cursor()
