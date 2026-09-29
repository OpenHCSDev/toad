"""Real incremental unread indexing paints pending, then exact counts, in both rosters/tabs."""

import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import wire
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad.session_tracker import ExactUnread, IndexingUnread
from toad.widgets.comms_sidebar import CommsSidebar, ThreadRow
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.virtual_channel_list import VirtualChannelList


async def check(virtual):
    with TemporaryDirectory(prefix="pending-unread-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"), XDG_STATE_HOME=str(root / "state"),
                          TOAD_BENCH_VIRTUAL_CHANNELS="1" if virtual else "0")
        session = root / "native.jsonl"
        records = 8192
        session.write_text((json.dumps({"type": "message", "message": {
            "role": "assistant", "content": "Retained unread reply"}}) + "\n") * records)
        comms = wire(root / "wire")
        comms.registry.declare(Thread("worker", frozenset({"indexing"}), str(root),
                                      session_file=str(session)))
        comms.owners.acquire_thread("worker", owner_pid=os.getpid())
        initial = comms.views.viewer_snapshot(str(root))
        assert "worker" in initial.thread_unread_pending
        assert "worker" not in initial.thread_unread
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause()
            mode = app.selected_mode
            screen = app.screen
            screen.on_comms_session_named("worker")
            sidebar = screen.query_one(CommsSidebar)
            sidebar.navigation.expanded["#all"] = True

            def row_text():
                if virtual:
                    listing = sidebar.query_one(VirtualChannelList)
                    return str(listing.get_option("member:#all:worker").prompt)
                return next(row for row in sidebar.query(ThreadRow)
                            if row.target_name == "worker").render().plain

            await sidebar.sync_sessions()
            await pilot.pause()
            assert "Indexing" in row_text(), row_text()
            assert isinstance(next(tab for tab in app.open_tabs if tab.mode_name == mode).unread, IndexingUnread)
            tab = screen.query_one(f"SessionLabel#{mode}", SessionLabel)
            assert "Indexing" in tab.render().plain, tab.render().plain
            assert "(0)" not in row_text() and "(0)" not in tab.render().plain
            async with asyncio.timeout(45):
                while "worker" in app._sidebar_snapshot.thread_unread_pending:
                    await sidebar.sync_sessions()
                    await pilot.pause(.02)
            await sidebar.sync_sessions()
            await pilot.pause()
            assert app._sidebar_snapshot.thread_unread["worker"] == records
            assert f"({records})" in row_text(), row_text()
            assert f"({records})" in tab.render().plain, tab.render().plain
            assert "Indexing" not in row_text() and "Indexing" not in tab.render().plain
            comms.views.mark_thread_view_read("worker", worktree=str(root),
                through=comms.transcripts.transcript_checkpoint("worker"))
            await sidebar.sync_sessions()
            await pilot.pause()
            assert next(tab for tab in app.open_tabs if tab.mode_name == mode).unread == ExactUnread()
            assert "Indexing" not in row_text() and f"({records})" not in row_text()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print(f"PASS {'virtual' if virtual else 'native'}: actual pending index → exact {records} → read zero, rows and tabs")


async def main():
    await check("--virtual" in sys.argv)


if __name__ == "__main__":
    asyncio.run(main())
