"""Durable session rows; SQLite and JSON are decoded only at this boundary."""

import asyncio
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from time import time_ns
from typing import Annotated, Self

from agent_comms.field_codec import PathText, RecordedTimestamp, TimestampText
from agent_comms.store_files import DEFAULT_ISOLATION
from agent_comms.typed_table import (
    Column, DurableTables, SharedFileTables, TableSchema, TextStorage, TypedTable,
    WriterOwnedFile, WriterOwnedStore,
)

from toad import paths
from toad.agent_schema import AgentDefinition
from toad.tab_identity import TabIdentity

SessionTimestamp = Annotated[RecordedTimestamp, TimestampText, Column(storage=TextStorage)]


def recorded_now() -> RecordedTimestamp:
    return RecordedTimestamp.written(datetime.now(UTC))


class ToadTables(SharedFileTables, DurableTables):
    """The database's durable rows share one declaration-derived schema."""


class ToadDatabase(WriterOwnedStore):
    """Toad's one durable file. The installer opens a copy of it with the target's
    declaration before cutover, so a stored schema Toad could not open fails the install."""

    @classmethod
    def path(cls) -> Path:
        return paths.get_state() / "toad.db"

    @classmethod
    def table_schema(cls) -> type[TableSchema]:
        return ToadTables


@dataclass(frozen=True)
class SessionMeta:
    cwd: Annotated[Path | None, PathText] = None
    # Saved external agent definition, also used when its catalog entry is gone.
    agent_data: AgentDefinition | None = None


@dataclass(frozen=True, kw_only=True)
class Session(ToadTables, TypedTable, declared_name="sessions"):
    id: Annotated[int | None, Column(primary_key=True, auto_increment=True)] = None
    agent: str
    agent_identity: str
    agent_session_id: str | None
    title: str
    protocol: str = "acp"
    prompt_count: int = 0
    created_at: SessionTimestamp = field(default_factory=recorded_now)
    last_used: SessionTimestamp = field(default_factory=recorded_now)
    # The column keeps the durable file name; its value is always typed metadata.
    meta_json: SessionMeta = field(default_factory=SessionMeta)


@dataclass(frozen=True)
class OpenTabRow(ToadTables, TypedTable, declared_name="open_tabs"):
    identity: Annotated[TabIdentity, Column(primary_key=True)]
    position: int


@dataclass(frozen=True)
class ModelHistory(ToadTables, TypedTable, declared_name="model_history"):
    agent_identity: Annotated[str, Column(primary_key=True)]
    model_id: Annotated[str, Column(primary_key=True)]
    last_used: int

    @classmethod
    def recent(cls, db: sqlite3.Connection, agent_identity: str, limit: int) -> list[Self]:
        return cls.read(db.execute(
            f'SELECT {cls._column_list(cls.columns())} FROM "{cls.declared_name}" '
            'WHERE agent_identity = ? ORDER BY last_used DESC, model_id LIMIT ?',
            (agent_identity, limit),
        ))

    def remember(self, db: sqlite3.Connection) -> None:
        """The first write serializes competing observations; older ones never replace newer use."""
        self.insert_if_absent(db)
        self.update(
            db,
            where="{agent_identity} = ? AND {model_id} = ? AND {last_used} < ?",
            parameters=(self.agent_identity, self.model_id, self.last_used),
            last_used=self.last_used,
        )


class DB:
    """Toad's durable state; its transaction owner runs off the UI thread."""

    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else ToadDatabase.path()

    def transaction[T](self, operation: Callable[[sqlite3.Connection], T]) -> T:
        with ToadDatabase.exclusive_writer(self.path, isolation_level=DEFAULT_ISOLATION) as db, db:
            return operation(db)

    async def _transaction[T](self, operation: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(self.transaction, operation)

    async def tab_roster(self, identities: tuple[TabIdentity, ...]) -> None:
        def write(db):
            OpenTabRow.delete(db)
            for position, identity in enumerate(identities):
                OpenTabRow(identity, position).upsert(db)

        await self._transaction(write)

    async def tab_list(self) -> list[OpenTabRow]:
        return await self._transaction(lambda db: OpenTabRow.select(
            db, order_by=("position",),
        ))

    async def record_model_usage(
        self, agent_identity: str, model_id: str, *, last_used: int | None = None,
    ) -> None:
        """Remember a confirmed selection or completed turn, never a highlight."""
        row = ModelHistory(agent_identity, model_id, time_ns() if last_used is None else last_used)
        await self._transaction(row.remember)

    async def recent_models(self, agent_identity: str, limit: int = 20) -> list[str]:
        """Return this agent's most recently used model IDs, newest first."""
        rows = await self._transaction(lambda db: ModelHistory.recent(db, agent_identity, limit))
        return [row.model_id for row in rows]

    async def create(self) -> None:
        await asyncio.to_thread(self.prepare)

    def prepare(self) -> None:
        self.transaction(lambda db: ToadDatabase.table_schema().install_schema(db, WriterOwnedFile()))

    async def session_new(
        self,
        title: str,
        agent: str,
        agent_identity: str,
        agent_session_id: str | None,
        protocol: str = "acp",
        meta: SessionMeta | None = None,
    ) -> int:
        row = Session(
            title=title,
            agent=agent,
            agent_identity=agent_identity,
            agent_session_id=agent_session_id,
            protocol=protocol,
            meta_json=meta if meta is not None else SessionMeta(),
        )
        def insert(db):
            identity = row.insert(db).lastrowid
            assert identity is not None, "A saved ACP session must have a SQLite row id"
            return identity

        return await self._transaction(insert)

    async def session_started(self, id: int, agent_session_id: str) -> None:
        await self._update_session(id, agent_session_id=agent_session_id)

    async def _update_session(self, id: int, **changes) -> None:
        def update(db):
            Session.update(db, where="id = ?", parameters=(id,), **changes)

        await self._transaction(update)

    async def session_update_last_used(self, id: int) -> None:
        await self._update_session(id, last_used=recorded_now())

    async def session_update_title(self, id: int, title: str) -> None:
        await self._update_session(id, title=title)

    async def session_update_project(self, id: int, cwd: Path) -> bool:
        def update(db):
            db.execute("BEGIN IMMEDIATE")
            row = Session.one(db, id=id)
            if row is None:
                return False
            Session.update(
                db,
                where="id = ?",
                parameters=(id,),
                meta_json=replace(row.meta_json, cwd=cwd),
            )
            return True

        return await self._transaction(update)

    async def session_get(self, id: int) -> Session | None:
        return await self._transaction(lambda db: Session.one(db, id=id))

    async def session_get_recent(self, max_results: int = 100) -> list[Session]:
        return await self._transaction(
            lambda db: Session.select(db, order_by=("last_used",), descending=True, limit=max_results),
        )
