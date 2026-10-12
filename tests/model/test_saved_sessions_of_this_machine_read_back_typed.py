"""Every session saved in this machine's Toad database reads back as a typed session with its identity, agent definition and directory intact, and reading changes nothing."""

import json
from pathlib import Path
import sqlite3

import pytest
from agent_comms.field_codec import FieldCodec

from toad.db import Session


def test_saved_sessions_keep_identity_agent_definition_and_directory(tmp_path):
    original = Path.home() / ".local/state/toad/toad.db"
    if not original.exists():
        pytest.skip("this machine has no saved Toad sessions")
    # Read only; the comparison runs on a SQLite backup owned by this test.
    with (
        sqlite3.connect(f"file:{original}?mode=ro", uri=True) as source,
        sqlite3.connect(tmp_path / "copy.db") as copied,
    ):
        source.backup(copied)
        raw = copied.execute("SELECT * FROM sessions ORDER BY id").fetchall()
        typed = Session.read(copied.execute("SELECT * FROM sessions ORDER BY id"))
        assert len(raw) == len(typed)
        for before, after in zip(raw, typed, strict=True):
            assert before[:7] == (after.id, after.agent, after.agent_identity, after.agent_session_id,
                                  after.title, after.protocol, after.prompt_count)
            saved = json.loads(before[9])["agent_data"]
            encoded = FieldCodec.encode(after.meta_json.agent_data)
            assert {key: encoded[key] for key in saved} == saved
            assert json.loads(before[9])["cwd"] == str(after.meta_json.cwd)
        assert copied.execute("SELECT * FROM sessions ORDER BY id").fetchall() == raw
