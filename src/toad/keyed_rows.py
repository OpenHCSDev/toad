"""Member reconciliation by the model's key, for every frontend.

`KeyedRows.reconcile_keys` decides which rows a container keeps, makes, refreshes, retires
and reorders for the model's keys; a frontend supplies only how its native container lists,
mounts, orders and drops a row: Textual's widgets (`toad.widgets.keyed_rows`) and Qt's tree
items (`toad.qt.window.QtChannelGroup`).
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Iterable


class KeyedRows[KeyT]:
    """Retain native member rows by model key; the container owns their order."""

    def keep_row(self, key: KeyT) -> bool:
        return False

    def should_mount(self, key: KeyT) -> bool:
        return True

    @abstractmethod
    def create_row(self, key: KeyT):
        ...

    def update_row(self, key: KeyT, row) -> None:
        pass

    def rows_changed(self) -> None:
        pass

    def place_row(self, row, index: int) -> None:
        """Publish list-position facts only for a new or moved row."""

    # What the frontend's container supplies

    @abstractmethod
    def member_order(self) -> Iterable:
        """The container's rows, in the order it shows them."""

    @abstractmethod
    def row_attached(self, row) -> bool:
        """Whether ``row`` is in the container now."""

    @abstractmethod
    def mount_rows(self, rows: Iterable) -> None:
        """Register one selected cohort with the native container."""

    @abstractmethod
    def order_rows(self, position: Callable[[object], int]) -> None:
        """Show the container's rows sorted by ``position``."""

    @abstractmethod
    def retire_row(self, row) -> None:
        """Drop ``row`` from the container."""

    def reconcile_keys(self, keys: Iterable[KeyT], *, changed: frozenset[KeyT]):
        keys = tuple(keys)
        rows = self.rows
        retained = set(rows.values())
        previous = {row: index for index, row in enumerate(row for row in self.member_order() if row in retained)}
        wanted = set(keys)
        retired = [key for key in rows if key not in wanted and not self.keep_row(key)]
        for key in retired:
            self.retire_row(rows.pop(key))
        mounted = []
        unattached = {}
        for key in keys:
            if key not in rows:
                if not self.should_mount(key):
                    continue
                current = self.create_row(key)
                rows[key] = current
                self.update_row(key, current)
                if not self.row_attached(current):
                    unattached[key] = current
                mounted.append(current)
            elif key in changed or (key not in unattached and not self.row_attached(rows[key])):
                self.update_row(key, rows[key])
        if unattached:
            self.mount_rows(unattached.values())
        ordered = tuple(rows[key] for key in keys if key in rows)
        positions = {row: index for index, row in enumerate(ordered)}
        for row, index in positions.items():
            if previous.get(row) != index:
                self.place_row(row, index)
        live = tuple(row for row in self.member_order() if row in positions)
        reordered = bool(ordered) and live != ordered
        if reordered:
            self.order_rows(lambda row: positions.get(row, len(positions)))
        if retired or mounted or reordered:
            self.rows_changed()
        return ordered
