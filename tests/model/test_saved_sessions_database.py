"""The saved-session database reads saved rows into typed sessions, writes typed metadata and waits for a busy writer off the event loop."""

from datetime import UTC, datetime
import asyncio
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
from agent_comms.repo import Checkout
from agent_comms.nominal.field_codec import RecordedTimestamp
from agent_comms.errors import RelationViolationError

from toad.agent_schema import AgentDefinition
from toad.db import DB, Session, SessionMeta

SAVED_AGENT = {"identity": "id", "name": "Agent", "run_command": {"*": "agent"}}


async def test_saved_row_reads_as_typed_session_and_updates_keep_its_agent(tmp_path):
    with patch("toad.db.paths.get_state", return_value=tmp_path):
        store = DB()
        await store.create()
        # A row as Toad saves it, in the STRICT schema DB.create declares.
        written = RecordedTimestamp.written(datetime.now(UTC)).text
        with sqlite3.connect(store.path) as db:
            db.execute(
                """INSERT INTO sessions
                (agent,agent_identity,agent_session_id,title,protocol,prompt_count,created_at,last_used,meta_json)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                ("Agent", "id", "session", "Saved", "acp", 0, written, written,
                 json.dumps({"cwd": str(tmp_path), "agent_data": SAVED_AGENT})),
            )
        before = await store.session_get(1)
        assert isinstance(before, Session)
        assert before.created_at.text == written
        assert before.prompt_count == 0
        assert before.meta_json.cwd == Checkout(tmp_path)
        assert await store.session_update_project(1, tmp_path / "changed")
        after = await store.session_get(1)
        assert after.meta_json.agent_data == before.meta_json.agent_data
        assert after.meta_json.cwd == Checkout(tmp_path / "changed")
        assert after.created_at == before.created_at
        await store.session_update_title(1, "Renamed")
        await store.session_update_last_used(1)
        assert (await store.session_get(1)).title == "Renamed"
        metadata = SessionMeta(Checkout(tmp_path), AgentDefinition.decode(SAVED_AGENT))
        pk = await store.session_new("New", "Agent", "id", "session2", meta=metadata)
        saved = await store.session_get(pk)
        assert saved.id == pk and saved.meta_json == metadata
        reopened = DB()
        await reopened.create()
        assert await reopened.session_get(pk) == saved
        assert len(await store.session_get_recent(1)) == 1
        with sqlite3.connect(store.path) as db:
            db.execute("UPDATE sessions SET meta_json='not metadata' WHERE id=1")
        with pytest.raises(ValueError):
            await store.session_get(1)


async def test_fresh_schema_stores_metadata_and_a_busy_writer_does_not_block_the_event_loop(tmp_path):
    with patch("toad.db.paths.get_state", return_value=tmp_path):
        store = DB()
        await store.create()
        pk = await store.session_new("New", "Agent", "id", "session", meta=SessionMeta(Checkout(Path("/project"))))
        assert (await store.session_get(pk)).meta_json.cwd == Checkout(Path("/project"))
        await store.record_model_usage("id", "model")
        assert await store.recent_models("id") == ["model"]
        # Busy persistence waits in its worker; the event loop keeps running
        # while a real SQLite writer holds the database.
        with sqlite3.connect(store.path) as holder:
            holder.execute("BEGIN IMMEDIATE")
            updating = asyncio.create_task(store.session_update_title(pk, "Updated"))
            await asyncio.wait_for(asyncio.sleep(0.03), 0.5)
            assert not updating.done()
            holder.commit()
            await updating
        assert (await store.session_get(pk)).title == "Updated"


async def test_incompatible_durable_schema_is_refused_with_its_rows_untouched(tmp_path):
    with patch("toad.db.paths.get_state", return_value=tmp_path):
        store = DB()
        with sqlite3.connect(store.path) as db:
            db.execute("CREATE TABLE sessions (id INTEGER, title TEXT NOT NULL)")
            db.execute("INSERT INTO sessions VALUES (NULL, 'Retain the original')")
            before = db.execute("SELECT rowid,* FROM sessions").fetchall()
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name='sessions'").fetchone()
        with pytest.raises(RelationViolationError, match="differs from its declaration"):
            await store.create()
        with sqlite3.connect(store.path) as db:
            assert db.execute("SELECT rowid,* FROM sessions").fetchall() == before
            assert db.execute("SELECT sql FROM sqlite_master WHERE name='sessions'").fetchone() == schema


async def test_sqlite_failure_is_not_reported_as_an_absent_session(tmp_path):
    with patch("toad.db.paths.get_state", return_value=tmp_path):
        store = DB()
        await store.create()
        assert await store.session_get(1234) is None
        with sqlite3.connect(store.path) as db:
            db.execute("DROP TABLE sessions")
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            await store.session_get(1234)
        with sqlite3.connect(store.path) as db:
            db.execute("DROP TABLE model_history")
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            await store.recent_models("id")
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            await store.record_model_usage("id", "model")


async def test_model_history_keeps_newest_use_per_agent_and_model_after_reopening(tmp_path):
    with patch("toad.db.paths.get_state", return_value=tmp_path):
        store = DB()
        await store.create()
        await asyncio.gather(*(
            store.record_model_usage("owner", "a", last_used=stamp)
            for stamp in (10, 30, 20)
        ))
        await store.record_model_usage("owner", "b", last_used=30)
        await store.record_model_usage("other", "foreign", last_used=40)
        await store.record_model_usage("owner", "a", last_used=1)
        reopened = DB()
        await reopened.create()
        assert await reopened.recent_models("owner") == ["a", "b"]
        assert await reopened.recent_models("owner", limit=1) == ["a"]
        assert await reopened.recent_models("other") == ["foreign"]
