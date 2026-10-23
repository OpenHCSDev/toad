"""One owner for logical open order and visited-tab navigation."""

from collections.abc import Callable, Collection, Mapping

from toad.core.events import CoreEventStream, TabHistoryChanged
from toad.db import DB
from toad.tab_identity import TabIdentity


class TabOrder:
    def __init__(
        self, focus: Callable[[TabIdentity, int | None], object], home: str, db: DB
    ) -> None:
        # What is shown while no tab is open.
        self.home = home
        self.db = db
        self.db.prepare()
        self._visits: list[TabIdentity] = []
        self._cursor = -1
        self._focus = focus
        self.events = CoreEventStream(self)

    def __contains__(self, mode: TabIdentity | None) -> bool:
        return mode in self.names

    @property
    def names(self) -> tuple[TabIdentity, ...]:
        return tuple(row.identity for row in self.db.tab_list())

    @property
    def recent(self) -> tuple[TabIdentity, ...]:
        """Visited sources first, derived from the existing navigation history."""
        return tuple(dict.fromkeys((*reversed(self._visits[:self._cursor + 1]), *self.names)))

    def open(self, mode: TabIdentity, *, after: TabIdentity | None = None) -> None:
        if mode in self:
            return
        order = list(self.names)
        insertion = order.index(after) + 1 if after in self else len(order)
        order.insert(insertion, mode)
        self.reorder(order)

    def reorder(self, modes: Collection[TabIdentity]) -> None:
        self.db.tab_reorder(tuple(modes))

    def project[T](self, values: Mapping[TabIdentity, T]) -> tuple[T, ...]:
        return tuple(values[mode] for mode in self.names if mode in values)

    def previous(self, current: TabIdentity, *, eligible: Collection[TabIdentity] | None = None) -> TabIdentity | None:
        """The tab to show on leaving ``current``; home once no tab is open."""
        opened = self.names
        if not opened:
            return None
        candidates = [
            mode
            for mode in opened
            if mode != current and (eligible is None or mode in eligible)
        ]
        preceding = (
            opened[: opened.index(current)] if current in self else opened
        )
        return next(
            (mode for mode in reversed(preceding) if mode in candidates),
            candidates[0] if candidates else current if current in self else opened[-1],
        )

    def history_target(self, direction: int) -> tuple[int, TabIdentity] | None:
        index = self._cursor + direction
        if 0 <= index < len(self._visits):
            return index, self._visits[index]
        return None

    def navigate(self, direction: int) -> None:
        if target := self.history_target(direction):
            index, mode = target
            if mode == self._visits[self._cursor]:
                self.record_visit(mode, index)
            else:
                self._focus(mode, index)

    def record_visit(self, mode: TabIdentity, history_index: int | None = None) -> None:
        if mode not in self:
            return
        if (
            history_index is not None
            and 0 <= history_index < len(self._visits)
            and self._visits[history_index] == mode
        ):
            self._cursor = history_index
        else:
            del self._visits[self._cursor + 1 :]
            self._visits.append(mode)
            self._cursor = len(self._visits) - 1
        self.events.publish(TabHistoryChanged())

    def close(self, modes: Collection[TabIdentity]) -> None:
        for mode in modes:
            self.db.tab_delete(mode)
        self.reorder(self.names)
        retained = []
        cursor = -1
        for index, mode in enumerate(self._visits):
            if mode in self:
                retained.append(mode)
                if index <= self._cursor:
                    cursor = len(retained) - 1
        if retained != self._visits:
            self._visits, self._cursor = retained, cursor
            self.events.publish(TabHistoryChanged())
