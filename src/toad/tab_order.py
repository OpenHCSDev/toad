"""One owner for logical open order and visited-tab navigation."""

import asyncio
from collections.abc import Callable, Collection, Mapping
from contextlib import asynccontextmanager

from agent_comms.child_process import join_retirement

from toad.core.events import CoreEventStream, TabHistoryChanged
from toad.db import DB
from toad.tab_identity import TabIdentity


class TabOrder:
    def __init__(
        self, focus: Callable[[TabIdentity, int | None], object], home: str, db: DB
    ) -> None:
        # What is shown while no tab is open.
        self.home = home
        self._db = db
        self._open: list[TabIdentity] = []
        self._write_lock = asyncio.Lock()
        self._visits: list[TabIdentity] = []
        self._cursor = -1
        self._focus = focus
        self.events = CoreEventStream(self)

    async def load(self) -> tuple[TabIdentity, ...]:
        async with self._write_lock:
            self._open = [row.identity for row in await self._db.tab_list()]
            return self.names

    @asynccontextmanager
    async def editing(self):
        async with self._write_lock:
            yield
            # A cancelled caller must join its SQLite writer before releasing the lock.
            await join_retirement(asyncio.create_task(self._db.tab_roster(self.names)))

    def __contains__(self, mode: TabIdentity | None) -> bool:
        return mode in self._open

    @property
    def names(self) -> tuple[TabIdentity, ...]:
        return tuple(self._open)

    @property
    def recent(self) -> tuple[TabIdentity, ...]:
        """Visited sources first, derived from the existing navigation history."""
        return tuple(dict.fromkeys((*reversed(self._visits[:self._cursor + 1]), *self.names)))

    async def open(self, mode: TabIdentity, *, after: TabIdentity | None = None) -> None:
        async with self.editing():
            if mode not in self:
                insertion = self._open.index(after) + 1 if after in self else len(self._open)
                self._open.insert(insertion, mode)

    async def reorder(self, modes: Collection[TabIdentity]) -> None:
        async with self.editing():
            self._open[:] = modes

    def project[T](self, values: Mapping[TabIdentity, T]) -> tuple[T, ...]:
        return tuple(values[mode] for mode in self.names if mode in values)

    def previous(
        self, current: TabIdentity, *, eligible: Collection[TabIdentity] | None = None
    ) -> TabIdentity | None:
        """The previous tab, or no tab when the roster is empty."""
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

    async def close(self, modes: Collection[TabIdentity]) -> None:
        async with self.editing():
            self._open[:] = (identity for identity in self._open if identity not in modes)
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
