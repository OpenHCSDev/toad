"""Native member reconciliation by the model's key."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable

from textual.widget import Widget


class KeyedRows[KeyT]:
    """Retain native member widgets by model key; the container owns their order."""

    def keep_row(self, key: KeyT) -> bool:
        return False

    def should_mount(self, key: KeyT) -> bool:
        return True

    @abstractmethod
    def create_row(self, key: KeyT):
        ...

    def update_row(self, key: KeyT, row) -> None:
        pass

    def retire_row(self, row: Widget) -> None:
        row.remove()

    def rows_changed(self) -> None:
        pass

    def place_row(self, row, index: int) -> None:
        """Publish list-position facts only for a new or moved row."""

    def reconcile_keys(self, keys: Iterable[KeyT], *, changed: frozenset[KeyT]):
        rows = self.rows
        retained = set(rows.values())
        previous = {
            row: index
            for index, row in enumerate(
                child for child in self.member_container.children if child in retained
            )
        }
        wanted = set(keys)
        retired = [key for key in rows if key not in wanted and not self.keep_row(key)]
        for key in retired:
            self.retire_row(rows.pop(key))
        mounted = []
        for key in keys:
            if key not in rows:
                if not self.should_mount(key):
                    continue
                current = self.create_row(key)
                rows[key] = current
                self.update_row(key, current)
                if not current.is_attached:
                    self.member_container.mount(current)
                mounted.append(current)
            elif key in changed or not rows[key].is_attached:
                self.update_row(key, rows[key])
        ordered = tuple(rows[key] for key in keys if key in rows)
        positions = {row: index for index, row in enumerate(ordered)}
        for row, index in positions.items():
            if previous.get(row) != index:
                self.place_row(row, index)
        live = tuple(
            child for child in self.member_container.children if child in positions
        )
        reordered = bool(ordered) and live != ordered
        if reordered:
            self.member_container.sort_children(
                key=lambda child: positions.get(child, len(positions))
            )
        if retired or mounted or reordered:
            self.rows_changed()
        return ordered
