"""Durable sessions, actual shell syntax, and T8 deletion guards."""

import ast
import asyncio
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from toad.danger import detect
from toad.db import DB, Session, SessionMeta

SOURCE = Path(__file__).resolve().parents[1] / "src/toad"


class SessionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_durable_database_and_typed_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("toad.db.paths.get_state", return_value=root):
                store = DB()
                # Current durable schema, as emitted before T8. This is saved
                # data acceptance, not support for an obsolete client API.
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
                        (
                            "Agent",
                            "id",
                            "session",
                            "Saved",
                            "acp",
                            json.dumps(
                                {
                                    "cwd": str(root),
                                    "agent_data": {
                                        "identity": "id",
                                        "run_command": {"*": "agent"},
                                    },
                                }
                            ),
                        ),
                    )
                self.assertTrue(await store.create())
                before = await store.session_get(1)
                self.assertIsInstance(before, Session)
                self.assertIsInstance(before.created_at, datetime)
                self.assertEqual(before.prompt_count, 0)
                self.assertEqual(before.meta_json.cwd, root)
                self.assertTrue(await store.session_update_project(1, root / "changed"))
                after = await store.session_get(1)
                self.assertEqual(
                    after.meta_json.agent_data, before.meta_json.agent_data
                )
                self.assertEqual(after.meta_json.cwd, root / "changed")
                self.assertEqual(after.created_at, before.created_at)
                await store.session_update_title(1, "Renamed")
                await store.session_update_last_used(1)
                self.assertEqual((await store.session_get(1)).title, "Renamed")
                metadata = SessionMeta(root, {"name": "Saved agent", "identity": "id"})
                pk = await store.session_new(
                    "New", "Agent", "id", "session2", meta=metadata
                )
                self.assertEqual((await store.session_get(pk)).meta_json, metadata)
                self.assertEqual(len(await store.session_get_recent(1)), 1)
                with sqlite3.connect(store.path) as db:
                    db.execute(
                        "UPDATE sessions SET prompt_count='not a count' WHERE id=1"
                    )
                with self.assertRaises(ValueError):
                    await store.session_get(1)

    async def test_fresh_schema_metadata_and_worker_transaction(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("toad.db.paths.get_state", return_value=Path(temporary)):
                store = DB()
                self.assertTrue(await store.create())
                pk = await store.session_new(
                    "New", "Agent", "id", "session", meta=SessionMeta(Path("/project"))
                )
                self.assertEqual(
                    (await store.session_get(pk)).meta_json.cwd, Path("/project")
                )
                self.assertTrue(await store.record_model_usage("id", "model"))
                self.assertEqual(await store.recent_models("id"), ["model"])
                # Busy persistence waits in its worker; UI event loop keeps
                # running while a real SQLite writer holds the database.
                with sqlite3.connect(store.path) as holder:
                    holder.execute("BEGIN IMMEDIATE")
                    updating = asyncio.create_task(
                        store.session_update_title(pk, "Updated")
                    )
                    await asyncio.wait_for(asyncio.sleep(0.03), 0.5)
                    self.assertFalse(updating.done())
                    holder.commit()
                    self.assertTrue(await updating)


class DangerBoundaryTests(unittest.TestCase):
    def test_real_shell_spans(self):
        cases = (
            ("rm -rf ../x", ((0, 11, "destructive"),)),
            ("rm tmp/x", ((0, 8, "danger"),)),
            ("ls", ()),
            ("cd ..; rm x", ((7, 11, "destructive"),)),
            ("echo hi > ../x", ((8, 14, "destructive"),)),
            ("cat < ../x", ()),
            ("rm -rf", ((0, 6, "danger"),)),
            ("ls | rm ../x", ((5, 12, "destructive"),)),
            ('echo "unterminated', ()),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                spans = detect(
                    "/project",
                    "/project",
                    command,
                    danger_style="danger",
                    destructive_style="destructive",
                )
                self.assertEqual(
                    tuple((span.start, span.end, span.style) for span in spans),
                    expected,
                )

    def test_substitution_directory_is_scoped(self):
        spans = detect(
            "/project",
            "/project",
            "echo $(cd ..; rm x); rm x",
            danger_style="danger",
            destructive_style="destructive",
        )
        self.assertEqual([span.style for span in spans], ["destructive", "danger"])


class DeletionGuards(unittest.TestCase):
    def test_terminal_environment_and_session_callers(self):
        variables = {
            "FORCE_COLOR",
            "TTY_COMPATIBLE",
            "TERM",
            "COLORTERM",
            "TOAD",
            "CLICOLOR",
        }
        for path in SOURCE.rglob("*.py"):
            if path.name == "terminal_environment.py":
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Subscript) and isinstance(
                            target.slice, ast.Constant
                        ):
                            self.assertNotIn(target.slice.value, variables, str(path))
                if (
                    isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "session"
                ):
                    self.fail(f"Untyped session row caller: {path}:{node.lineno}")
        store = (SOURCE / "db.py").read_text()
        self.assertNotIn("cast(Session", store)
        self.assertNotIn("promot_count", store)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS sessions", store)

    def test_danger_old_dispatch_deleted(self):
        source = (SOURCE / "danger.py").read_text()
        self.assertNotIn("hasattr", source)
        self.assertNotIn(".kind", source)
        self.assertNotIn("IntEnum", source)
        self.assertNotIn("max(", source)
        self.assertFalse((SOURCE / "widgets/danger_warning.py").exists())
        self.assertNotIn("_danger_level", (SOURCE / "widgets/prompt.py").read_text())


if __name__ == "__main__":
    unittest.main()
