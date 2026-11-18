"""The shared keyed reconciliation over a Textual container's member widgets."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from textual.widget import Widget

from toad.keyed_rows import KeyedRows


class WidgetKeyedRows[KeyT](KeyedRows[KeyT]):
    """Rows are the member container's child widgets."""

    def member_order(self) -> Iterable[Widget]:
        return self.member_container.children

    def row_attached(self, row: Widget) -> bool:
        return row.is_attached

    def mount_row(self, row: Widget) -> None:
        self.member_container.mount(row)

    def order_rows(self, position: Callable[[object], int]) -> None:
        self.member_container.sort_children(key=position)

    def retire_row(self, row: Widget) -> None:
        row.remove()
