"""One owner for logical open order and visited-tab navigation."""

import asyncio
from collections.abc import Callable, Collection, Mapping
from contextlib import asynccontextmanager

from agent_comms.execution.child_process import join_retirement

from toad.core.events import CoreEventStream, TabHistoryChanged
from toad.db import DB, TabScope
from toad.tab_identity import TabIdentity


class TabOrder:
    def __init__(
        self, focus: Callable[[TabIdentity], object], home: str, db: DB,
        scopes: tuple[TabScope, ...],
    ) -> None:
        # What is shown while no tab is open.
        self.home = home
        self._db = db
        # The Core this app is connected to owns these tabs; others' rows stay untouched.
        self._scopes = scopes
        self._open: list[TabIdentity] = []
        self._write_lock = asyncio.Lock()
        self._visits: list[TabIdentity] = []
        self._cursor = -1
        self._focus = focus
        self.events = CoreEventStream(self)

    async def load(self) -> tuple[TabIdentity, ...]:
        async with self._write_lock:
            self._open = [row.identity for row in await self._db.tab_list(self._scopes)]
            return self.names

    @asynccontextmanager
    async def editing(self):
        async with self._write_lock:
            before = self.names
            yield
            if self.names != before:
                # A cancelled caller must join its SQLite writer before releasing the lock.
                await join_retirement(asyncio.create_task(self._db.tab_roster(self._scopes, self.names)))

    def __contains__(self, mode: TabIdentity | None) -> bool:
        return mode in self._open

    @property
    def scopes(self) -> tuple[TabScope, ...]:
        """The saved tabs this app's Core owns."""
        return self._scopes

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

    def project[T](self, values: Mapping[TabIdentity, T]) -> tuple[T, ...]:
        return tuple(values[mode] for mode in self.names if mode in values)

    async def move(self, identity: TabIdentity, direction: int) -> None:
        """Move the original tab one position without changing visit history."""
        async with self.editing():
            if identity not in self:
                return
            index = self._open.index(identity)
            destination = index + direction
            if 0 <= destination < len(self._open):
                self._open.insert(destination, self._open.pop(index))

    def previous(
        self, current: TabIdentity, *, eligible: Collection[TabIdentity] | None = None
    ) -> str:
        """The previous tab's mode, or home when the roster is empty."""
        opened = self.names
        if not opened:
            return self.home
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
        ).mode_name

    def history_target(self, direction: int) -> tuple[int, TabIdentity] | None:
        index = self._cursor + direction
        if 0 <= index < len(self._visits):
            return index, self._visits[index]
        return None

    def navigate(self, direction: int) -> None:
        """The cursor moves when the step is taken: a switch runs over several frames, and
        a second step taken meanwhile counts from this one, not from where it started."""
        if target := self.history_target(direction):
            index, mode = target
            switching = mode != self._visits[self._cursor]
            self._cursor = index
            self.events.publish(TabHistoryChanged())
            if switching:
                self._focus(mode)

    def came_from(self, current: TabIdentity) -> str:
        """The tab selected before ``current``: the newest other visit, then the open tabs;
        with no other tab, back stays where it is, and with none open it goes home."""
        return next(
            (mode.mode_name for mode in self.recent if mode != current),
            current.mode_name if current in self else self.home,
        )

    def record_visit(self, mode: TabIdentity) -> None:
        """A new visit: it drops the steps ahead of the cursor and becomes the newest."""
        if mode not in self:
            return
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
