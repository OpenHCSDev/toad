"""Saved tabs belong to the Core their app is connected to. A laptop's local Toad and a remote
Toad on ts-gaming share one toad.db and the same root path (~/.agent-comms), and each roster
write once deleted every row, so opening a tab in one wiped the other's saved tabs."""

import sqlite3

from toad.comms_root import LocalCoreConnection
from toad.db import DB, TabScope, UNSCOPED_TABS
from toad.tab_identity.kinds import PreviewTab


# Both machines' roots have the same path; which machine's home it sits in is not the point.
ROOT = "/srv/core/.agent-comms"

# A mailbox tab exactly as a live toad.db stored it before tabs had a scope.
SAVED_MAILBOX = ('{"kind":"mailbox","key":{"name":"claude-laptop","created_at":1793929021.25345},'
                 f'"root":"{ROOT}"}}')

LOCAL, REMOTE = TabScope(ROOT), TabScope("https://ts-gaming.example/mcp")


async def test_one_cores_roster_write_keeps_the_other_cores_tabs(tmp_path):
    database = DB(tmp_path / "toad.db")
    await database.create()
    local_tab, remote_tab = PreviewTab(tmp_path / "local"), PreviewTab(tmp_path / "remote")
    await database.tab_roster((LOCAL,), (local_tab,))
    await database.tab_roster((REMOTE,), (remote_tab,))
    await database.tab_roster((LOCAL,), (local_tab,))
    assert [row.identity for row in await database.tab_list((LOCAL,))] == [local_tab]
    assert [row.identity for row in await database.tab_list((REMOTE,))] == [remote_tab]


def test_a_local_connection_owns_tabs_saved_before_scopes_and_a_remote_one_does_not(tmp_path):
    assert LocalCoreConnection(tmp_path).tab_scopes() == (TabScope(str(tmp_path)), UNSCOPED_TABS)


async def test_tabs_saved_before_scopes_carry_onto_the_scoped_table(tmp_path):
    path = tmp_path / "toad.db"
    with sqlite3.connect(path) as db:
        # The declaration toad.db stored before tabs had a scope, read from a live toad.db.
        db.execute('CREATE TABLE "open_tabs" ("identity" TEXT NOT NULL, "position" INTEGER NOT NULL, '
                   'PRIMARY KEY ("identity")) STRICT')
        db.execute('INSERT INTO "open_tabs" VALUES (?, 0)', (SAVED_MAILBOX,))
    database = DB(path)
    await database.create()
    with sqlite3.connect(path) as db:
        columns = [row[1] for row in db.execute('PRAGMA table_info("open_tabs")')]
    assert "scope" in columns
    rows = await database.tab_list((UNSCOPED_TABS,))
    assert [row.identity.key.name for row in rows] == ["claude-laptop"]
    assert [row.scope for row in rows] == [UNSCOPED_TABS]


async def test_two_cores_holding_the_same_tab_identity_each_keep_their_own(tmp_path):
    """Both buses sit at ~/.agent-comms, so one mailbox identity can be saved by both Cores;
    neither roster write may move the other's row."""
    database = DB(tmp_path / "toad.db")
    await database.create()
    shared = PreviewTab(tmp_path / "shared")
    await database.tab_roster((LOCAL,), (shared,))
    await database.tab_roster((REMOTE,), (PreviewTab(tmp_path / "first"), shared))
    assert [row.identity for row in await database.tab_list((LOCAL,))] == [shared]
    assert [(row.identity, row.position) for row in await database.tab_list((REMOTE,))] == [
        (PreviewTab(tmp_path / "first"), 0), (shared, 1)]
