"""The saved-session database reads saved rows into typed sessions, writes typed metadata and waits for a busy writer off the event loop."""

from datetime import datetime
import asyncio
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from toad.agent_schema import AgentDefinition
from toad.db import DB, Session, SessionMeta

SAVED_AGENT = {"identity": "id", "name": "Agent", "run_command": {"*": "agent"}}


async def test_saved_row_reads_as_typed_session_and_updates_keep_its_agent(tmp_path):
    with patch("toad.db.paths.get_state", return_value=tmp_path):
        store = DB()
        # A row in the current durable schema, with the agent definition as Toad saves it.
        with sqlite3.connect(store.path) as db:
            db.execute("""CREATE TABLE sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              agent TEXT NOT NULL, agent_identity TEXT NOT NULL,
              agent_session_id TEXT NOT NULL, title TEXT NOT NULL,
              protocol TEXT NOT NULL, prompt_count INTEGER DEFAULT 0,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              meta_json TEXT DEFAULT '{}')""")
            db.execute(
                """INSERT INTO sessions
                (agent,agent_identity,agent_session_id,title,protocol,meta_json)
                VALUES (?,?,?,?,?,?)""",
                ("Agent", "id", "session", "Saved", "acp",
                 json.dumps({"cwd": str(tmp_path), "agent_data": SAVED_AGENT})),
            )
        assert await store.create()
        before = await store.session_get(1)
        assert isinstance(before, Session)
        assert isinstance(before.created_at, datetime)
        assert before.prompt_count == 0
        assert before.meta_json.cwd == tmp_path
        assert await store.session_update_project(1, tmp_path / "changed")
        after = await store.session_get(1)
        assert after.meta_json.agent_data == before.meta_json.agent_data
        assert after.meta_json.cwd == tmp_path / "changed"
        assert after.created_at == before.created_at
        await store.session_update_title(1, "Renamed")
        await store.session_update_last_used(1)
        assert (await store.session_get(1)).title == "Renamed"
        metadata = SessionMeta(tmp_path, AgentDefinition.decode(SAVED_AGENT))
        pk = await store.session_new("New", "Agent", "id", "session2", meta=metadata)
        assert (await store.session_get(pk)).meta_json == metadata
        assert len(await store.session_get_recent(1)) == 1
        with sqlite3.connect(store.path) as db:
            db.execute("UPDATE sessions SET prompt_count='not a count' WHERE id=1")
        with pytest.raises(ValueError):
            await store.session_get(1)


async def test_fresh_schema_stores_metadata_and_a_busy_writer_does_not_block_the_event_loop(tmp_path):
    with patch("toad.db.paths.get_state", return_value=tmp_path):
        store = DB()
        assert await store.create()
        pk = await store.session_new("New", "Agent", "id", "session", meta=SessionMeta(Path("/project")))
        assert (await store.session_get(pk)).meta_json.cwd == Path("/project")
        assert await store.record_model_usage("id", "model")
        assert await store.recent_models("id") == ["model"]
        # Busy persistence waits in its worker; the event loop keeps running
        # while a real SQLite writer holds the database.
        with sqlite3.connect(store.path) as holder:
            holder.execute("BEGIN IMMEDIATE")
            updating = asyncio.create_task(store.session_update_title(pk, "Updated"))
            await asyncio.wait_for(asyncio.sleep(0.03), 0.5)
            assert not updating.done()
            holder.commit()
            assert await updating
