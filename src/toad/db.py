"""Durable session rows; SQLite and JSON are decoded only at this boundary."""

import asyncio
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from time import time_ns
from typing import Any

import aiosqlite
from agent_comms.field_codec import FieldCodec
from agent_comms.typed_table import Column, JsonStorage, SqlStorage, TypedTable

from toad import paths

MODEL_HISTORY_SCHEMA = """
    CREATE TABLE IF NOT EXISTS model_history (
        agent_identity TEXT NOT NULL,
        model_id TEXT NOT NULL,
        last_used INTEGER NOT NULL,
        PRIMARY KEY (agent_identity, model_id)
    )
"""


class SessionCodec(FieldCodec):
    """Session paths and timestamps retain their existing text encoding."""

    @classmethod
    def encode(cls, value):
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return super().encode(value)

    @classmethod
    def _decode(cls, target, data):
        if target is Path:
            return Path(super()._decode(str, data))
        if target is datetime:
            return datetime.fromisoformat(super()._decode(str, data))
        return super()._decode(target, data)


class SessionTimestampStorage(SqlStorage):
    sql_type = "TEXT"
    codec = SessionCodec

    @classmethod
    def accepts(cls, annotation):
        return annotation is datetime


@dataclass(frozen=True)
class SessionMeta:
    cwd: Path | None = None
    # Saved external agent definition, also used when its catalog entry is gone.
    agent_data: dict[str, Any] | None = None


class SessionMetaStorage(JsonStorage):
    codec = SessionCodec

    @classmethod
    def accepts(cls, annotation):
        return annotation is SessionMeta


@dataclass(frozen=True, kw_only=True)
class Session(TypedTable, declared_name="sessions"):
    id: int | None = field(
        default=None, metadata={"sql": Column(primary_key=True, auto_increment=True)}
    )
    agent: str
    agent_identity: str
    agent_session_id: str
    title: str
    protocol: str = "acp"
    prompt_count: int = 0
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
        metadata={"sql": Column(storage=SessionTimestampStorage)},
    )
    last_used: datetime = field(
        default_factory=lambda: datetime.now(UTC),
        metadata={"sql": Column(storage=SessionTimestampStorage)},
    )
    # The column keeps the durable file name; its value is always typed metadata.
    meta_json: SessionMeta = field(
        default_factory=SessionMeta,
        metadata={"sql": Column(storage=SessionMetaStorage)},
    )


class DB:
    """Toad's durable state; session transactions run entirely off the UI thread."""

    def __init__(self):
        self.path = paths.get_state() / "toad.db"

    def open(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.path)

    async def _sessions[T](
        self, operation: Callable[[sqlite3.Connection], T], failure: T
    ) -> T:
        def transaction():
            try:
                with closing(sqlite3.connect(self.path)) as db, db:
                    return operation(db)
            except sqlite3.Error:
                return failure

        return await asyncio.to_thread(transaction)

    async def record_model_usage(self, agent_identity: str, model_id: str) -> bool:
        """Remember a confirmed selection or completed turn, never a highlight."""
        try:
            async with self.open() as db:
                await db.execute(MODEL_HISTORY_SCHEMA)
                await db.execute(
                    """INSERT INTO model_history (agent_identity, model_id, last_used)
                    VALUES (?, ?, ?) ON CONFLICT(agent_identity, model_id)
                    DO UPDATE SET last_used = excluded.last_used""",
                    (agent_identity, model_id, time_ns()),
                )
                await db.commit()
        except aiosqlite.Error:
            return False
        return True

    async def recent_models(self, agent_identity: str, limit: int = 20) -> list[str]:
        """Return this agent's most recently used model IDs, newest first."""
        try:
            async with self.open() as db:
                await db.execute(MODEL_HISTORY_SCHEMA)
                cursor = await db.execute(
                    """SELECT model_id FROM model_history WHERE agent_identity = ?
                    ORDER BY last_used DESC, model_id LIMIT ?""",
                    (agent_identity, limit),
                )
                return [row[0] for row in await cursor.fetchall()]
        except aiosqlite.Error:
            return []

    async def create(self) -> bool:
        def create(db):
            if (
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (Session.declared_name,),
                ).fetchone()
                is None
            ):
                Session.create(db)
            return True

        return await self._sessions(create, False)

    async def session_new(
        self,
        title: str,
        agent: str,
        agent_identity: str,
        agent_session_id: str,
        protocol: str = "acp",
        meta: SessionMeta | None = None,
    ) -> int | None:
        row = Session(
            title=title,
            agent=agent,
            agent_identity=agent_identity,
            agent_session_id=agent_session_id,
            protocol=protocol,
            meta_json=meta if meta is not None else SessionMeta(),
        )
        return await self._sessions(lambda db: row.insert(db).lastrowid, None)

    async def _update_session(self, id: int, **changes) -> bool:
        def update(db):
            Session.update(db, where="id = ?", parameters=(id,), **changes)
            return True

        return await self._sessions(update, False)

    async def session_update_last_used(self, id: int) -> bool:
        return await self._update_session(id, last_used=datetime.now(UTC))

    async def session_update_title(self, id: int, title: str) -> bool:
        return await self._update_session(id, title=title)

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

        return await self._sessions(update, False)


    async def session_get(self, id: int) -> Session | None:
        return await self._sessions(lambda db: Session.one(db, id=id), None)

    async def session_get_recent(self, max_results: int = 100) -> list[Session] | None:
        return await self._sessions(
            lambda db: Session.read(
                db.execute(
                    f'SELECT {Session._column_list(Session.columns())} FROM "{Session.declared_name}" ORDER BY last_used DESC LIMIT ?',
                    (max_results,),
                )
            ),
            None,
        )
