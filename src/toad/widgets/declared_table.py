"""A keyed table whose columns and cells come from record declarations."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import get_type_hints

from agent_comms.field_codec import FieldCodec
from formbridge.forms.ui_utils import FieldDisplayText
from python_introspect import declared_field_label
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
        plans = tuple(plan for plan in FieldCodec.field_plans(self.record)
                      if plan.records and not plan.excluded_in(self.view))
        projections = FieldCodec.projections(self.record, self.view)
        self.readers: dict[str, Callable[[R], object]] = {
            plan.name: plan.current for plan in plans
        } | {name: member.fget for name, member in projections.items()}
        self.annotations = {plan.name: plan.annotation for plan in plans} | {
            name: get_type_hints(member.fget, include_extras=True)["return"]
            for name, member in projections.items()
        }
        self.records: dict[RowKey, R] = {}
        self.entity_keys: dict[DisclosureKey, RowKey] = {}

    def on_mount(self) -> None:
        for name, annotation in self.annotations.items():
            label = declared_field_label(annotation) or FieldDisplayText.from_field_name(name).display_name
            self.add_column(label, key=name)

    def row_tone(self, record: R) -> type[ThemeColour]:
        return ForegroundColour

    def cells(self, record: R) -> tuple[Content, ...]:
        return tuple(DisclosedValue.of(read(record)).cell() for read in self.readers.values())

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
        for key in self.records.keys() - incoming.keys():
            self.remove_row(key)
        for key, record in incoming.items():
            if key in self.records and self.records[key] == record:
                continue
            colour = self.app.colours.colour(self.row_tone(record))
            style = Style(background=colour, foreground=colour.get_contrast_text())
            cells = tuple(cell.stylize(style) for cell in self.cells(record))
            if key in self.rows:
                for name, cell in zip(self.readers, cells):
                    self.update_cell(key, name, cell)
            else:
                self.add_row(*cells, key=key, height=None)
        self.records = incoming
        self.entity_keys = keys
        # DataTable has no public keyed reorder. Its own sort() uses this same index;
        # retain Core's supplied order without inventing another state sort in the UI.
        self._row_locations = TwoWayDict({key: index for index, key in enumerate(incoming)})
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
        flexible = available - len(columns)
        total = sum(weights)
        used = 0
        for column, weight in zip(columns, weights):
            end = used + weight
            column.auto_width = False
            column.width = 1 + flexible * end // total - flexible * used // total
            used = end
        # Auto-height is native DataTable behavior, but it must be invalidated when
        # column widths or current cell text change, not only when a row is first added.
        for row in self.rows.values():
            row.height = 0
        self._new_rows.update(self.rows)
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
