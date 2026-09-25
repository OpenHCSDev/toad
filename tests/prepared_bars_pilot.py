"""Bar consumers share worker content and finish the newest roster before return."""

import asyncio
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from agent_comms import Thread, wire

from runtime_fixture import ToadApp
from toad.sidebar_preparation import TabRosterWork, ThreadRowInput, ThreadRowsWork
from toad.widgets.session_tabs import SessionLabel, SessionsTabs


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-prepared-bars-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        comms.register(Thread("worker", frozenset({"shared"}), str(root)))
        person = comms.viewer_snapshot(str(root), show_stopped=True).threads[0]
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(130, 43)) as pilot:
            await pilot.pause()
            calls = []
            original = ThreadRowsWork.prepare

            def counted(work):
                calls.append(threading.get_ident())
                return original(work)

            with patch.object(ThreadRowsWork, "prepare", counted):
                left, right = await asyncio.gather(*[
                    app.preparation.submit(ThreadRowsWork((ThreadRowInput(person, unread=17),)))
                    for _ in range(2)
                ])
                assert len(calls) == 1 and calls[0] != threading.get_ident()
                assert left is not right and left[0].frames[0].plain == right[0].frames[0].plain
                changed = await app.preparation.submit(ThreadRowsWork((ThreadRowInput(person, unread=18),)))
                assert len(calls) == 2 and changed[0].frames[0].plain.startswith("(18)")

            tabs = app.screen.query_one(SessionsTabs)
            entered, release = asyncio.Event(), asyncio.Event()
            original_submit = app.preparation.submit
            delayed = False

            async def gated(work):
                nonlocal delayed
                if isinstance(work, TabRosterWork) and not delayed:
                    delayed = True
                    entered.set()
                    await release.wait()
                return await original_submit(work)

            try:
                with patch.object(app.preparation, "submit", gated):
                    tabs._last_tabs = None
                    synchronization = asyncio.create_task(tabs._sync_tabs())
                    await asyncio.wait_for(entered.wait(), 5)
                    app.session_tracker.update_session(app.current_mode, title="New authoritative roster title")
                    release.set()
                    await asyncio.wait_for(synchronization, 5)
                    assert tabs._last_tabs == app.open_tabs
                    expected = next(tab for tab in app.open_tabs if tab.mode_name == app.current_mode)
                    assert tabs.query_one(f"#{app.current_mode}", SessionLabel).render().plain == expected.title
            finally:
                release.set()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("prepared bars: shared worker rows, independent deliveries, changed inputs, newest roster before readiness OK")


if __name__ == "__main__":
    asyncio.run(main())
